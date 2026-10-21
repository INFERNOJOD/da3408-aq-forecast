import json

from scripts import push_stage_metrics as script


def write(tmp_path, name, **extra):
    rec = {"stage": name, "run_id": "r1", "status": "success",
           "started_at": "2026-10-20T16:13:23", "duration_s": 10.0,
           "rows_per_sec": 3.0, **extra}  # fmt: skip
    (tmp_path / f"{name}.json").write_text(json.dumps(rec))
    return rec


def test_pushes_every_record_with_its_end_time(tmp_path, monkeypatch):
    sent = []
    monkeypatch.setattr(
        script,
        "push_metrics",
        lambda r, u, success_time: sent.append((r, u, success_time)) or True,
    )
    rec = write(tmp_path, "ingest")
    write(tmp_path, "train")
    assert script.main(["--url", "http://pg:9091", "--dir", str(tmp_path)]) == 0
    assert [r["stage"] for r, _, _ in sent] == ["ingest", "train"]
    assert sent[0][1] == "http://pg:9091"
    assert sent[0][2] == script.end_time(rec)
    assert script.end_time(rec) - script.end_time({**rec, "duration_s": 0}) == 10.0


def test_empty_dir_and_bad_record_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(script, "push_metrics", lambda *a, **k: True)
    assert script.main(["--dir", str(tmp_path)]) == 1
    (tmp_path / "bad.json").write_text("{not json")
    write(tmp_path, "ingest")
    assert script.main(["--dir", str(tmp_path)]) == 1  # one bad file is reported


def test_unreachable_pushgateway_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(script, "push_metrics", lambda *a, **k: False)
    write(tmp_path, "ingest")
    assert script.main(["--dir", str(tmp_path)]) == 1
