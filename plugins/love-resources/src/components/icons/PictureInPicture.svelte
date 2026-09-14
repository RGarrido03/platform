<script lang="ts">
  export let size: 'small' | 'medium' | 'large'
  export let fill: string = 'currentColor'
</script>

<svg class="svg-{size}" {fill} viewBox="0 0 20 20" xmlns="http://www.w3.org/2000/svg">
  <path
    fill-rule="evenodd"
    clip-rule="evenodd"
    d="M3.75 4.5h12.5c.69 0 1.25.56 1.25 1.25v8.5c0 .69-.56 1.25-1.25 1.25H3.75c-.69 0-1.25-.56-1.25-1.25v-8.5c0-.69.56-1.25 1.25-1.25Zm.5 1.75v7.5h11.5v-7.5H4.25Z"
  />
  <path d="M10.75 10.25h4.5c.41 0 .75.34.75.75v2.25c0 .41-.34.75-.75.75h-4.5c-.41 0-.75-.34-.75-.75V11c0-.41.34-.75.75-.75Z" />
</svg>
