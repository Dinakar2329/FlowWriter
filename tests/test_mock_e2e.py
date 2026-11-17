from __future__ import annotations
import subprocess
import sys
import socket
import time
from flowwriter.provider import ChatClient
from flowwriter.domain import Provider


def test_real_http_against_mock():
    proc = subprocess.Popen(
        [sys.executable, "scripts/mock_provider.py"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        alive = False
        for _ in range(50):
            try:
                with socket.create_connection(("127.0.0.1", 8765), timeout=0.2):
                    alive = True
                    break
            except OSError:
                time.sleep(0.04)
        assert alive
        for stream in (False, True):
            profile = Provider("mock", "Mock", "http://127.0.0.1:8765/v1", "mock-text-model", stream)
            text = ChatClient().generate(profile, "", "Summarize", "Some test words")
            assert "Some test words" in text
    finally:
        proc.terminate()
        proc.wait(timeout=5)
