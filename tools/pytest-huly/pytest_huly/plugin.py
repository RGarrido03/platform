"""
pytest-huly Plugin
Intercepts pytest test execution and syncs results to Huly Test Management.
"""

import os
import subprocess
import datetime
from typing import Optional
import pytest

from .client import HulyClient, generate_huly_id


def pytest_addoption(parser):
    group = parser.getgroup("huly", "Huly Test Management integration")
    group.addoption("--huly", action="store_true", default=False, help="Enable automatic Huly test reporting")
    group.addoption("--huly-url", default=None, help="Huly Transactor URL (e.g. http://localhost:3332)")
    group.addoption("--huly-workspace", default=None, help="Huly Workspace UUID")
    group.addoption("--huly-token", default=None, help="Huly Personal Access Token / API Token")
    group.addoption("--huly-project", default=None, help="Huly TestProject Space ID (24-hex)")
    group.addoption("--huly-run-name", default=None, help="Custom title for the created TestRun")
    group.addoption("--huly-ingest-url", default=None, help="Optional huly-test-ingest microservice URL")
    group.addoption("--huly-no-auto-create", action="store_true", default=False, help="Do not auto-create missing TestCases")


class HulyReporter:
    def __init__(self, config):
        self.config = config
        self.url = config.getoption("--huly-url") or os.getenv("HULY_URL", "http://localhost:3332")
        self.workspace = config.getoption("--huly-workspace") or os.getenv("HULY_WORKSPACE", "")
        self.token = config.getoption("--huly-token") or os.getenv("HULY_TOKEN", "")
        self.project = config.getoption("--huly-project") or os.getenv("HULY_PROJECT", "")
        self.run_name = config.getoption("--huly-run-name")
        self.ingest_url = config.getoption("--huly-ingest-url") or os.getenv("HULY_INGEST_URL")
        self.auto_create = not config.getoption("--huly-no-auto-create")
        self.run_id = generate_huly_id()
        self.results = []
        self.client = HulyClient(
            base_url=self.url,
            workspace_id=self.workspace,
            api_token=self.token,
            ingest_service_url=self.ingest_url,
        )

    def get_git_info(self) -> str:
        try:
            branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
            commit = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True, stderr=subprocess.DEVNULL).strip()
            return f"{branch} @ {commit}"
        except Exception:
            return "ci"

    def pytest_sessionstart(self, session):
        git_info = self.get_git_info()
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if not self.run_name:
            self.run_name = f"Pytest Run - {now} ({git_info})"
        print(f"\n[Huly] Initializing TestRun '{self.run_name}' (ID: {self.run_id})")

    @pytest.hookimpl(hookwrapper=True)
    def pytest_runtest_makereport(self, item, call):
        outcome = yield
        rep = outcome.get_result()

        # Only record during execution call or if setup failed
        if rep.when == "call" or (rep.when == "setup" and rep.failed):
            marker = item.get_closest_marker("huly")
            marker_case_id = marker.kwargs.get("case_id") if marker else None
            marker_suite = marker.kwargs.get("suite") if marker else None

            # 0: Untested, 1: Blocked, 2: Passed, 3: Failed
            if rep.passed:
                status = 2
            elif rep.failed:
                status = 3
            else:
                status = 1

            error_trace = None
            if rep.failed and rep.longrepr:
                error_trace = str(rep.longrepr)

            suite_name = marker_suite or item.module.__name__
            self.results.append({
                "name": item.name,
                "suite_name": suite_name,
                "case_id": marker_case_id,
                "status": status,
                "duration": rep.duration,
                "error_trace": error_trace,
            })

    def pytest_sessionfinish(self, session, exitstatus):
        if not self.results:
            return

        print(f"\n[Huly] Synchronizing {len(self.results)} test results to Huly Test Management...")
        try:
            if self.ingest_url:
                self.client.sync_via_ingest_service(
                    project_id=self.project,
                    run_name=self.run_name,
                    run_id=self.run_id,
                    results=self.results,
                    auto_create=self.auto_create,
                )
            else:
                self.client.sync_via_transactor(
                    project_id=self.project,
                    run_name=self.run_name,
                    run_id=self.run_id,
                    results=self.results,
                    auto_create=self.auto_create,
                )
            print(f"[Huly] Successfully synced TestRun {self.run_id}!")
        except Exception as e:
            print(f"[Huly] Warning: Failed to sync test results to Huly: {e}")
        finally:
            self.client.close()


def pytest_configure(config):
    if config.getoption("--huly", default=False):
        reporter = HulyReporter(config)
        config.pluginmanager.register(reporter, "huly_reporter")
