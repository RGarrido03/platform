const esbuild = require('esbuild')
const path = require('path')
const fs = require('fs')
const { execSync } = require('child_process')

const SCRIPT_DIR = __dirname

const defaultConfig = {
  entryPoint: 'src/index.ts',
  outdir: 'bundle',
  platform: 'node',
  minify: false,
  keepNames: false,
  sourcemap: false,
  logLevel: 'error',
  external: ['snappy'],
  define: {}
}

function getGitRevision() {
  try {
    return '"' + execSync('git describe --all --long').toString().trim() + '"'
  } catch (error) {
    console.warn('Failed to get git revision:', error.message)
    return ''
  }
}

function getVersionFromScript(scriptPath) {
  try {
    const absoluteScriptPath = path.resolve(SCRIPT_DIR, scriptPath)
    return execSync(`node "${absoluteScriptPath}"`).toString().trim()
  } catch (error) {
    console.warn(`Failed to get version from ${scriptPath}:`, error.message)
    return ''
  }
}

// The release of the stack this image is deployed into (huly-selfhost's HULY_VERSION), without
// the leading "v"; undefined when it is not set.
function getReleaseVersion() {
  const release = (process.env.HULY_VERSION ?? '').trim().replace(/^v/, '')
  return release !== '' ? JSON.stringify(release) : undefined
}

async function bundle(config) {
  // Ensure output directory exists
  fs.mkdirSync(config.outdir, { recursive: true })

  try {
    await esbuild.build({
      entryPoints: [config.entryPoint],
      bundle: true,
      platform: config.platform,
      outfile: path.join(config.outdir, 'bundle.js'),
      logLevel: config.logLevel,
      minify: config.minify,
      keepNames: config.keepNames,
      sourcemap: config.sourcemap,
      external: config.external,
      define: config.define
    })

    console.log('Build completed successfully!')
  } catch (error) {
    console.error('Build failed:', error.message)
    process.exit(1)
  }
}

async function main() {
  const args = process.argv.slice(2)
  const config = { ...defaultConfig }

  const define = {}

  args.forEach((arg) => {
    if (arg.startsWith('--')) {
      const [key, value] = arg.slice(2).split('=')
      switch (key) {
        case 'entry':
          config.entryPoint = value
          break
        case 'minify':
          config.minify = value !== 'false'
          break
        case 'keep-names':
          config.keepNames = value !== 'false'
          break
        case 'external':
          config.external.push(value)
          break
        case 'sourcemap':
          config.sourcemap = value !== 'false'
          break
        case 'define':
          define[value] = true
          break
      }
    }
  })

  // Upstream builds every image from one release tag, so all of them advertise the same app
  // and model version. This fork ships custom images next to released hardcoreeng/* images, so
  // its bundles have no release tag on their lineage and would advertise a stale version, which
  // the front/server and front/workspace-model version guards reject. --define=RELEASE_VERSION
  // makes a bundle advertise the release it is deployed into (HULY_VERSION) instead of its own
  // checkout. Only bundles the browser talks to (the front) should use it: for server-side
  // bundles MODEL_VERSION gates workspace model upgrades and must stay this checkout's own.
  const releaseVersion = define.RELEASE_VERSION ? getReleaseVersion() : undefined

  const env = {
    MODEL_VERSION: define.MODEL_VERSION
      ? releaseVersion ?? getVersionFromScript('./show_version.js')
      : undefined,
    VERSION: releaseVersion ?? getVersionFromScript('./show_tag.js'),
    GIT_REVISION: define.GIT_REVISION ? getGitRevision() : undefined
  }

  Object.entries(env).forEach(([key, value]) => {
    if (value) {
      config.define[`process.env.${key}`] = value
    }
  })

  await bundle(config)
}

main().catch((error) => {
  console.error('Unexpected error:', error)
  process.exit(1)
})
