import test_encoding_smoke as _encoding


def test_encoding_scan_excludes_environment_but_keeps_application_files(tmp_path, monkeypatch):
    vendor = tmp_path / ".venv" / "Lib" / "site-packages"
    vendor.mkdir(parents=True)
    (vendor / "external.py").write_bytes(b"\xff")
    source = tmp_path / "core"
    source.mkdir()
    (source / "app.py").write_bytes(b"\xff")
    monkeypatch.chdir(tmp_path)
    paths = list(_encoding.TestEncodingSmoke()._iter_repo_text_files())
    assert [path.as_posix() for path in paths] == ["core/app.py"]
    # Excluding the environment must not turn off detection in application code.
    try:
        paths[0].read_text(encoding="utf-8")
    except UnicodeDecodeError:
        pass
    else:
        raise AssertionError("invalid source encoding must remain visible")
