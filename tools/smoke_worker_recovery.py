"""Opt-in EC2 worker/API restart test using only its own test account/document.

Stops/restarts API and worker, so run during a demo maintenance window.
Usage: python tools/smoke_worker_recovery.py --base-url http://32.236.61.231
"""
import argparse
import secrets
import subprocess
import time
from pathlib import Path
import httpx


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--ssh-target", default="ubuntu@32.236.61.231")
    parser.add_argument("--ssh-key", default=str(Path(__file__).resolve().parents[2] / "amgen-key.pem"))
    args = parser.parse_args()

    def remote(command):
        subprocess.run(["ssh", "-i", args.ssh_key, args.ssh_target,
                        "cd ~/amgen-poc && " + command], check=True, timeout=120)

    username, password = "recovery_" + secrets.token_hex(5), secrets.token_urlsafe(30)
    with httpx.Client(base_url=args.base_url, timeout=35) as client:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            try:
                if client.get('/api/health/ready').status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(2)
        else:
            raise RuntimeError('API not ready for restart test')
        client.post("/api/register", json={"username": username, "email": username + "@example.com", "password": password}).raise_for_status()
        token = client.post("/api/token", data={"username": username, "password": password})
        token.raise_for_status()
        client.headers["Authorization"] = "Bearer " + token.json()["access_token"]
        job_id = None
        try:
            remote("docker compose stop -t 10 worker")
            # Enough chunks to interrupt midway without any real patient data.
            text = "\n\n".join(f"Section {index}. In this invented follow-up record, a participant reports mild dizziness and denies chest pain. Blood pressure is 160/95 mmHg. No emergency treatment was required. This record is demonstration data. " * 2 for index in range(8))
            response = client.post("/api/upload", files={"file": ("worker-recovery-test.txt", text.encode(), "text/plain")}, headers={"Idempotency-Key": "recovery-upload"})
            response.raise_for_status()
            job_id = response.json()["job_id"]
            assert client.get(f"/api/jobs/{job_id}").json()["status"] == "queued"
            remote("docker compose restart -t 10 api")
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                try:
                    state = client.get(f"/api/jobs/{job_id}")
                    if state.status_code == 200:
                        assert state.json()["status"] == "queued"
                        break
                except httpx.HTTPError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("API did not recover")
            repeated = client.post("/api/upload", files={"file": ("worker-recovery-test.txt", text.encode(), "text/plain")}, headers={"Idempotency-Key": "recovery-upload"})
            assert repeated.json()["job_id"] == job_id
            print("PASS queued job and idempotency survive API restart", flush=True)
            remote("docker compose start worker")
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                state = client.get(f"/api/jobs/{job_id}").json()
                if state["successful_chunks"] >= 1 and state["status"] == "processing":
                    break
                if state["status"] in ("failed", "completed", "completed_with_errors"):
                    raise RuntimeError("Job ended before interruption")
                time.sleep(0.5)
            else:
                raise RuntimeError("Worker did not begin processing")
            remote("docker compose kill -s SIGKILL worker")
            print("PASS API responded while worker was embedding/extracting; worker killed after a checkpoint", flush=True)
            remote("docker compose up -d worker")
            deadline = time.monotonic() + 360
            while time.monotonic() < deadline:
                response = client.get(f"/api/jobs/{job_id}")
                response.raise_for_status()
                state = response.json()
                if state["status"] in ("completed", "completed_with_errors", "failed"):
                    assert state["status"] == "completed", state
                    assert state["attempts"] == 2, state
                    break
                time.sleep(2)
            else:
                raise RuntimeError("Worker did not recover within six minutes")
            document = client.get(f"/api/documents/{job_id}").json()
            indices = [chunk["chunk_index"] for chunk in document["chunks"]]
            assert len(indices) == state["total_chunks"] == len(set(indices))
            assert len(state["result_ids"]) == state["total_chunks"]
            print("PASS crash recovery resumed checkpoints with no duplicate chunks", flush=True)
            print(f"PASS {state['total_chunks']} chunks, {state['attempts']} attempts", flush=True)
        finally:
            remote("docker compose up -d api worker frontend")
            if job_id:
                state = client.get(f"/api/jobs/{job_id}").json()
                if state["status"] in ("completed", "completed_with_errors", "failed"):
                    deleted = client.delete(f"/api/documents/{job_id}")
                    if deleted.status_code not in (200, 404):
                        deleted.raise_for_status()


if __name__ == "__main__":
    main()
