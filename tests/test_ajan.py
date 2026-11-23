"""
test_ajan.py - ajan aracının birim ve entegrasyon testleri.
GERÇEK agy ikilisi çağrılmadan, sahte agy (fake_agy) ile test edilir.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from typing import Any
import pytest

import ajan
from ajan import (
    DEFAULT_MODEL,
    add_permissions,
    extract_dogrulama_ozet,
    extract_file_path,
    extract_rapor,
    get_settings_path,
    get_state_root,
    is_pid_alive,
    path_covers,
    resolve_model,
)

AJAN_PY = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "ajan.py"))


DEFAULT_FAKE_MODELS_OUTPUT = """Fetching available models...
gemini-4-neon-high\tGemini 4 Neon (High)
gemini-4-neon-xhigh\tGemini 4 Neon (XHigh)
gemini-4-neon-medium\tGemini 4 Neon (Medium)
gemini-4-neon-low\tGemini 4 Neon (Low)
gemini-4-argon-medium\tGemini 4 Argon (Medium)
gemini-4-hydrogen-xhigh\tGemini 4 Hydrogen (XHigh)
gemini-pro-orchestrator-neon\tOrchestrator (Neon)
gemini-3.8-flash-high\tGemini 3.8 Flash (High)
claude-opus-5-5-high\tClaude Opus 5.5 (High)
gpt-oss-120b-medium\tGPT-OSS 120B (Medium)
"""


def _write_fake_agy(target_dir: Any) -> tuple[str, str, str]:
    """Sahte agy ikilisini hedef dizine yazar; (betik, log, models_log) döner."""
    log_file = target_dir / "fake_agy.log"
    models_log_file = target_dir / "fake_agy_models.log"
    script_file = target_dir / "fake_agy.py"

    code = f"""#!/usr/bin/env python3
import json
import os
import sys
import time

log_file = {repr(str(log_file))}
models_log_file = {repr(str(models_log_file))}
default_models_out = {repr(DEFAULT_FAKE_MODELS_OUTPUT)}

# `agy models` çağrısı: fake_agy.log'a yazmadan ayrı log'a kaydet
if len(sys.argv) >= 2 and sys.argv[1] == "models":
    with open(models_log_file, "a", encoding="utf-8") as mf:
        mf.write(json.dumps({{"argv": sys.argv[1:]}}) + "\\n")
    if os.environ.get("FAKE_AGY_MODELS_FAIL") == "1":
        sys.stderr.write("ERROR: failed to fetch models\\n")
        sys.exit(1)
    models_file = os.environ.get("FAKE_AGY_MODELS")
    if models_file and os.path.isfile(models_file):
        with open(models_file, "r", encoding="utf-8") as src:
            sys.stdout.write(src.read())
    else:
        sys.stdout.write(default_models_out)
    sys.exit(0)

mode = os.environ.get("FAKE_AGY_MODE", "success")

# Argümanları kaydet
with open(log_file, "a", encoding="utf-8") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "cwd": os.getcwd()}}) + "\\n")

# --conversation argümanı kontrolü
conv_id = "fake-conv-uuid-123"
for i, arg in enumerate(sys.argv):
    if arg == "--conversation" and i + 1 < len(sys.argv):
        conv_id = sys.argv[i + 1]

if mode == "sleep":
    init_ev = {{"event": "init", "conversation_id": conv_id, "init": {{"model": "test-model"}}}}
    print(json.dumps(init_ev), flush=True)
    step_ev = {{
        "event": "step_update",
        "step_update": {{
            "conversation_id": conv_id,
            "step_index": 1,
            "state": "ACTIVE",
            "step_type": "tool",
            "tool_name": "read_file",
            "tool_info": {{"parameters": {{"Path": "/tmp/sleep_test.py"}}}},
        }}
    }}
    print(json.dumps(step_ev), flush=True)
    # Bekle (sinyalleri kabul et)
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        sys.exit(0)

elif mode == "error":
    init_ev = {{"event": "init", "conversation_id": conv_id, "init": {{"model": "test-model"}}}}
    print(json.dumps(init_ev), flush=True)
    res_ev = {{
        "event": "result",
        "result": {{
            "conversation_id": conv_id,
            "status": "ERROR",
            "response": "Kritik bir hata meydana geldi.",
            "duration_seconds": 0.5,
        }}
    }}
    print(json.dumps(res_ev), flush=True)
    sys.stderr.write("ERROR: Model çalışma hatası oluştu\\n")
    sys.exit(1)

elif mode == "varied_keys":
    init_ev = {{"event": "init", "conversation_id": conv_id, "init": {{"model": "test-model"}}}}
    print(json.dumps(init_ev), flush=True)

    # Farklı parametre anahtarlarıyla write_file adımları
    tools = [
        ("write_file", {{"Path": "/workspace/path1.py"}}),
        ("edit_file", {{"TargetFile": "/workspace/target2.py"}}),
        ("replace_file_content", {{"AbsolutePath": "/workspace/abs3.py"}}),
        ("write_to_file", {{"path": "/workspace/path4.py"}}),
        ("custom_write", {{"file_path": "/workspace/filepath5.py"}}),
        ("save_file", {{"dest": "/workspace/custom6.py"}}),
        ("run_command", {{"CommandLine": "pytest -v"}}),
    ]
    for idx, (t_name, params) in enumerate(tools, start=1):
        step_ev = {{
            "event": "step_update",
            "step_update": {{
                "conversation_id": conv_id,
                "step_index": idx,
                "state": "DONE",
                "step_type": "tool",
                "tool_name": t_name,
                "tool_info": {{"parameters": params}},
                "usage": {{"input_tokens": 10 * idx, "output_tokens": 5 * idx, "total_tokens": 15 * idx}}
            }}
        }}
        print(json.dumps(step_ev), flush=True)

    res_ev = {{
        "event": "result",
        "result": {{
            "conversation_id": conv_id,
            "status": "SUCCESS",
            "response": "Tüm adımlar tamamlandı.\\n```json\\n{{\\"ozet\\": \\"Parametre anahtarları test edildi.\\", \\"degisen_dosyalar\\": [\\"/workspace/path1.py\\"], \\"calistirilan_testler\\": [\\"pytest -v: PASSED\\"], \\"acik_konular\\": [], \\"basarili\\": true}}\\n```",
            "duration_seconds": 1.2,
            "usage": {{"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}}
        }}
    }}
    print(json.dumps(res_ev), flush=True)

elif mode == "no_json_block":
    init_ev = {{"event": "init", "conversation_id": conv_id, "init": {{"model": "test-model"}}}}
    print(json.dumps(init_ev), flush=True)
    res_ev = {{
        "event": "result",
        "result": {{
            "conversation_id": conv_id,
            "status": "SUCCESS",
            "response": "Bu yanıtta JSON bloğu bulunmamaktadır, serbest metin raporudur.",
            "duration_seconds": 0.8,
            "usage": {{"input_tokens": 50, "output_tokens": 20, "total_tokens": 70}}
        }}
    }}
    print(json.dumps(res_ev), flush=True)

elif mode == "fix_on_second_turn":
    init_ev = {{"event": "init", "conversation_id": conv_id, "init": {{"model": "test-model"}}}}
    print(json.dumps(init_ev), flush=True)
    fix_file = os.environ.get("FAKE_AGY_FIX_FILE", "")
    is_followup = any(arg == "--conversation" for arg in sys.argv)
    if is_followup and fix_file:
        try:
            with open(fix_file, "w", encoding="utf-8") as ff:
                ff.write("duzeltildi\\n")
        except Exception:
            pass
        step_ev = {{
            "event": "step_update",
            "step_update": {{
                "conversation_id": conv_id,
                "step_index": 1,
                "state": "DONE",
                "step_type": "tool",
                "tool_name": "write_file",
                "tool_info": {{"parameters": {{"Path": fix_file}}}},
            }}
        }}
        print(json.dumps(step_ev), flush=True)
    res_ev = {{
        "event": "result",
        "result": {{
            "conversation_id": conv_id,
            "status": "SUCCESS",
            "response": "İşlem yapıldı.\\n```json\\n{{\\"ozet\\": \\"Düzeltildi\\", \\"degisen_dosyalar\\": [], \\"calistirilan_testler\\": [], \\"acik_konular\\": [], \\"basarili\\": true}}\\n```",
            "duration_seconds": 0.5,
        }}
    }}
    print(json.dumps(res_ev), flush=True)

elif mode == "cumulative_duration":
    init_ev = {{"event": "init", "conversation_id": conv_id, "init": {{"model": "test-model"}}}}
    print(json.dumps(init_ev), flush=True)
    is_followup = any(arg == "--conversation" for arg in sys.argv)
    dur = 25584.0 if is_followup else 2.5
    res_ev = {{
        "event": "result",
        "result": {{
            "conversation_id": conv_id,
            "status": "SUCCESS",
            "response": "İşlem tamamlandı.\\n```json\\n{{\\"ozet\\": \\"Tamam\\", \\"degisen_dosyalar\\": [], \\"calistirilan_testler\\": [], \\"acik_konular\\": [], \\"basarili\\": true}}\\n```",
            "duration_seconds": dur,
        }}
    }}
    print(json.dumps(res_ev), flush=True)

else:
    # default success
    init_ev = {{"event": "init", "conversation_id": conv_id, "init": {{"model": "test-model"}}}}
    print(json.dumps(init_ev), flush=True)
    step1 = {{
        "event": "step_update",
        "step_update": {{
            "conversation_id": conv_id,
            "step_index": 1,
            "state": "DONE",
            "step_type": "tool",
            "tool_name": "write_file",
            "tool_info": {{"parameters": {{"Path": "/tmp/test_cikti.py"}}}},
            "usage": {{"input_tokens": 80, "output_tokens": 20, "total_tokens": 100}}
        }}
    }}
    print(json.dumps(step1), flush=True)
    res_ev = {{
        "event": "result",
        "result": {{
            "conversation_id": conv_id,
            "status": "SUCCESS",
            "response": "Görev tamamlandı.\\n```json\\n{{\\"ozet\\": \\"Sonuç başarılı.\\", \\"degisen_dosyalar\\": [\\"/tmp/test_cikti.py\\"], \\"calistirilan_testler\\": [\\"pytest: PASSED\\"], \\"acik_konular\\": [], \\"basarili\\": true}}\\n```",
            "duration_seconds": 1.0,
            "usage": {{"input_tokens": 120, "output_tokens": 40, "total_tokens": 160}}
        }}
    }}
    print(json.dumps(res_ev), flush=True)
"""
    script_file.write_text(code, encoding="utf-8")
    script_file.chmod(script_file.stat().st_mode | stat.S_IEXEC)
    return str(script_file), str(log_file), str(models_log_file)


@pytest.fixture(autouse=True)
def isolate_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """
    Tüm testler için varsayılan ortamı izole eder.
    Gerçek ~/.gemini, ~/.local/state/ajan ve gerçek agy erişimini engeller.
    """
    temp_dir = tmp_path_factory.mktemp("safe_default")
    safe_state = temp_dir / "safe_state"
    safe_settings = temp_dir / "gemini" / "settings.json"
    safe_agy_dir = temp_dir / "safe_agy"
    safe_state.mkdir(parents=True, exist_ok=True)
    safe_settings.parent.mkdir(parents=True, exist_ok=True)
    safe_agy_dir.mkdir(parents=True, exist_ok=True)
    safe_settings.write_text(
        json.dumps({"permissions": {"allow": []}}), encoding="utf-8"
    )
    default_fake_bin, _, _ = _write_fake_agy(safe_agy_dir)

    monkeypatch.setenv("AJAN_DIZIN", str(safe_state))
    monkeypatch.setenv("AJAN_AYAR", str(safe_settings))
    monkeypatch.setenv("AJAN_AGY", default_fake_bin)
    monkeypatch.setenv("AJAN_DIL", "tr")
    monkeypatch.delenv("AJAN_MODEL", raising=False)
    monkeypatch.delenv("FAKE_AGY_MODELS", raising=False)
    monkeypatch.delenv("FAKE_AGY_MODELS_FAIL", raising=False)
    ajan._CATALOG_MEMO.clear()


# ---------------------------------------------------------------------------
# Sahte agy Fixture
# ---------------------------------------------------------------------------
@pytest.fixture
def fake_agy(tmp_path: Any) -> tuple[str, str]:
    """
    Sahte agy ikilisi betiği oluşturur.
    Argümanları fake_agy.log dosyasına JSON olarak kaydeder.
    FAKE_AGY_MODE değişkenine göre stream-json davranışı sergiler.
    """
    script_file, log_file, _ = _write_fake_agy(tmp_path)
    return script_file, log_file


@pytest.fixture
def test_env(tmp_path: Any, fake_agy: tuple[str, str]) -> dict[str, Any]:
    """Testler için yalıtılmış ortam ve dizinleri hazırlar."""
    fake_bin, log_path = fake_agy
    models_log_path = os.path.join(
        os.path.dirname(log_path), "fake_agy_models.log"
    )
    state_dir = tmp_path / "ajan_state"
    settings_dir = tmp_path / "gemini_config"
    settings_path = settings_dir / "settings.json"

    state_dir.mkdir(parents=True, exist_ok=True)
    settings_dir.mkdir(parents=True, exist_ok=True)

    # Başlangıçta boş izinler
    settings_path.write_text(
        json.dumps({"permissions": {"allow": []}}, indent=2), encoding="utf-8"
    )

    env = os.environ.copy()
    env["AJAN_AGY"] = fake_bin
    env["AJAN_DIZIN"] = str(state_dir)
    env["AJAN_AYAR"] = str(settings_path)
    env["AJAN_DIL"] = "tr"
    env["FAKE_AGY_LOG"] = log_path
    env.pop("AJAN_MODEL", None)
    env.pop("FAKE_AGY_MODELS", None)
    env.pop("FAKE_AGY_MODELS_FAIL", None)

    return {
        "env": env,
        "state_dir": state_dir,
        "settings_path": settings_path,
        "log_path": log_path,
        "models_log_path": models_log_path,
    }


def run_ajan(
    args: list[str], env: dict[str, str], timeout: float = 10.0
) -> subprocess.CompletedProcess[str]:
    """ajan komutunu yalıtılmış ortamda çalıştırır."""
    assert "AJAN_AYAR" in env, "AJAN_AYAR ortam değişkeni tanımlı olmalı!"
    assert "AJAN_DIZIN" in env, "AJAN_DIZIN ortam değişkeni tanımlı olmalı!"
    assert not env["AJAN_AYAR"].startswith(
        os.path.expanduser("~/.gemini")
    ), "Gerçek ~/.gemini dizinine dokunulamaz!"
    assert not env["AJAN_DIZIN"].startswith(
        os.path.expanduser("~/.local/state/ajan")
    ), "Gerçek ~/.local/state/ajan dizinine dokunulamaz!"

    return subprocess.run(
        [sys.executable, AJAN_PY] + args,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


# ---------------------------------------------------------------------------
# Birim Testler: Fonksiyonel Mantık
# ---------------------------------------------------------------------------
def test_model_takma_adlari() -> None:
    """Model takma adlarının doğru çözümlendiğini doğrular."""
    assert DEFAULT_MODEL == "gemini-4-neon-xhigh"
    assert resolve_model("neon") == "gemini-4-neon-xhigh"
    assert resolve_model("neon-high") == "gemini-4-neon-high"
    assert resolve_model("neon-orta") == "gemini-4-neon-medium"
    assert resolve_model("flash") == "gemini-3.8-flash-high"
    assert resolve_model("flash-orta") == "gemini-3.8-flash-medium"
    assert resolve_model("argon") == "gemini-4-argon-high"
    assert resolve_model("argon-orta") == "gemini-4-argon-medium"
    assert resolve_model("hydrogen") == "gemini-4-hydrogen-xhigh"
    assert resolve_model("hydrogen-high") == "gemini-4-hydrogen-high"
    assert resolve_model("hydrogen-orta") == "gemini-4-hydrogen-medium"
    assert resolve_model(None) == "gemini-4-neon-xhigh"
    assert resolve_model("claude-sonnet-5-5-high") == "claude-sonnet-5-5-high"


def test_path_covers_mantigi() -> None:
    """path_covers fonksiyonunun alt yolları doğru eşleştirdiğini test eder."""
    assert path_covers("/home/user/project", "/home/user/project")
    assert path_covers("/home/user/project", "/home/user/project/sub/file.py")
    assert not path_covers("/home/user/project/sub", "/home/user/project")
    assert not path_covers("/home/user/other", "/home/user/project")


def test_yazilan_dosya_yolu_cikarimi_parametreleri() -> None:
    """
    Parametre anahtar adları araçtan araca değiştiğinde (Path, TargetFile,
    AbsolutePath, path, file_path ve '/' ile başlayanlar) doğru çıkarıldığını test eder.
    """
    assert (
        extract_file_path({"Path": "/workspace/dosya1.py"})
        == "/workspace/dosya1.py"
    )
    assert (
        extract_file_path({"TargetFile": "/workspace/dosya2.py"})
        == "/workspace/dosya2.py"
    )
    assert (
        extract_file_path({"AbsolutePath": "/workspace/dosya3.py"})
        == "/workspace/dosya3.py"
    )
    assert (
        extract_file_path({"path": "/workspace/dosya4.py"})
        == "/workspace/dosya4.py"
    )
    assert (
        extract_file_path({"file_path": "/workspace/dosya5.py"})
        == "/workspace/dosya5.py"
    )
    # Anahtar listede yoksa, '/' ile başlayan değer kontrol edilir
    assert (
        extract_file_path({"hedef_dosya": "/workspace/ozel.txt", "adet": 42})
        == "/workspace/ozel.txt"
    )
    # Hiçbir yol yoksa None döner
    assert extract_file_path({"text": "merhaba"}) is None


def test_rapor_cikarma_ve_fallback() -> None:
    """JSON bloğu olan ve olmayan yanıtlardan rapor çıkarımını test eder."""
    # 1. Başarılı JSON bloğu
    text1 = """
    İnceleme tamamlandı.
    ```json
    {
        "ozet": "Testler başarıyla geçti",
        "degisen_dosyalar": ["a.py", "b.py"],
        "calistirilan_testler": ["colcon test: passed"],
        "acik_konular": [],
        "basarili": true
    }
    ```
    """
    r1 = extract_rapor(text1, ["a.py"], ["colcon test"])
    assert r1["basarili"] is True
    assert r1["ozet"] == "Testler başarıyla geçti"
    assert "b.py" in r1["degisen_dosyalar"]

    # 2. JSON bloğu içermeyen serbest metin (fallback: basarili: None)
    text2 = "Kod refaktör edildi ancak JSON bloğu eklenmedi."
    r2 = extract_rapor(text2, ["c.py"], ["ls"])
    assert r2["basarili"] is None
    assert "Kod refaktör" in r2["ozet"]
    assert r2["degisen_dosyalar"] == ["c.py"]
    assert r2["calistirilan_testler"] == ["ls"]


# ---------------------------------------------------------------------------
# Entegrasyon Testleri (Sahte agy ile CLI Akışları)
# ---------------------------------------------------------------------------
def test_baslat_bekle_bitti_ve_rapor(test_env: dict[str, Any]) -> None:
    """
    baslat -> bekle -> bitti döngüsü ve rapor.json çıkarımı testi.
    """
    env = test_env["env"]
    state_dir = test_env["state_dir"]

    # baslat ve bekle
    res = run_ajan(
        ["baslat", "gorev1", "-m", "İlk deneme", "--bekle"], env=env
    )
    assert res.returncode == 0, f"Hata çıktısı: {res.stderr}"

    task_dir = state_dir / "gorev1"
    assert task_dir.is_dir()

    # meta.json kontrolü
    meta_path = task_dir / "meta.json"
    assert meta_path.is_file()
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["durum"] == "bitti"
    assert meta["conversation_id"] == "fake-conv-uuid-123"
    assert meta["token_toplami"]["total_tokens"] > 0

    # yanit.md kontrolü
    yanit_path = task_dir / "yanit.md"
    assert yanit_path.is_file()
    assert "Görev tamamlandı." in yanit_path.read_text(encoding="utf-8")

    # rapor.json kontrolü
    rapor_path = task_dir / "rapor.json"
    assert rapor_path.is_file()
    rapor = json.loads(rapor_path.read_text(encoding="utf-8"))
    assert rapor["basarili"] is True
    assert rapor["ozet"] == "Sonuç başarılı."

    # rapor komutunun okunabilir çıktısı
    res_rapor = run_ajan(["rapor", "gorev1"], env=env)
    assert res_rapor.returncode == 0
    assert "Başarılı: Evet" in res_rapor.stdout
    assert "Sonuç başarılı." in res_rapor.stdout

    # rapor --ham çıktısı
    res_ham = run_ajan(["rapor", "gorev1", "--ham"], env=env)
    assert res_ham.returncode == 0
    assert "Görev tamamlandı." in res_ham.stdout


def test_ayni_etiket_calisirken_ret(test_env: dict[str, Any]) -> None:
    """
    Bir etiket canlı çalışırken aynı etiketle yeni görev başlatmanın
    çıkış kodu 3 ile reddedildiğini test eder.
    """
    env = test_env["env"]
    env["FAKE_AGY_MODE"] = "sleep"

    # İlk görevi arka planda başlat
    res1 = run_ajan(["baslat", "mesgul_gorev", "-m", "Uyu"], env=env)
    assert res1.returncode == 0

    # Bekçinin agy'yi başlatması için kısa süre tanı
    time.sleep(0.6)

    # Aynı etiketle tekrar başlat
    res2 = run_ajan(
        ["baslat", "mesgul_gorev", "-m", "İkinci deneme"], env=env
    )
    assert res2.returncode == 3
    assert "canlı çalışıyor" in res2.stderr

    # Görevi iptal et
    run_ajan(["iptal", "mesgul_gorev"], env=env)


def test_eksik_izin_cikis_2_ve_onerilen_kural(test_env: dict[str, Any]) -> None:
    """
    settings.json'da kapsayan kural yoksa çıkış 2 verip
    önerilen kuralları listelediğini test eder.
    """
    env = test_env["env"]
    yaz_yol = "/var/custom/workspace"
    komut = "colcon build"

    res = run_ajan(
        [
            "baslat",
            "izin_testi",
            "-m",
            "Test",
            "--yaz",
            yaz_yol,
            "--komut",
            komut,
        ],
        env=env,
    )
    assert res.returncode == 2
    assert f"write_file({yaz_yol})" in res.stderr
    assert f"command({komut})" in res.stderr


def test_izin_ekle_yedekleyip_ekler(test_env: dict[str, Any]) -> None:
    """
    --izin-ekle bayrağının settings.json.bak-<zaman> yedeği alarak
    izinleri eklediğini ve görevi başarıyla başlattığını test eder.
    """
    env = test_env["env"]
    settings_path = test_env["settings_path"]
    yaz_yol = "/tmp/izin_ekle_dizin"
    komut = "pytest -k unit"

    res = run_ajan(
        [
            "baslat",
            "izin_ekle_gorev",
            "-m",
            "İzinli görev",
            "--yaz",
            yaz_yol,
            "--komut",
            komut,
            "--izin-ekle",
            "--bekle",
        ],
        env=env,
    )
    assert res.returncode == 0

    # Yedek dosyasının oluştuğunu doğrula
    bak_files = list(settings_path.parent.glob("settings.json.bak-*"))
    assert len(bak_files) >= 1

    # settings.json dosyasının güncellendiğini doğrula
    data = json.loads(settings_path.read_text(encoding="utf-8"))
    allow_rules = data["permissions"]["allow"]
    assert f"write_file({yaz_yol})" in allow_rules
    assert f"command({komut})" in allow_rules


def test_devam_ikinci_turda_conversation_gecer(
    test_env: dict[str, Any]
) -> None:
    """
    devam komutunun aynı conversation_id ile yeni tur başlattığını
    ve agy CLI'a --conversation parametresini geçtiğini test eder.
    """
    env = test_env["env"]
    log_path = test_env["log_path"]

    # 1. Tur
    res1 = run_ajan(
        ["baslat", "tur_gorev", "-m", "1. Tur İsteği", "--bekle"], env=env
    )
    assert res1.returncode == 0

    # 2. Tur
    res2 = run_ajan(
        ["devam", "tur_gorev", "-m", "2. Tur Takip Mesajı", "--bekle"], env=env
    )
    assert res2.returncode == 0

    # agy'ye iletilen argümanları kontrol et
    with open(log_path, "r", encoding="utf-8") as f:
        calls = [json.loads(line) for line in f if line.strip()]

    assert len(calls) == 2
    second_call_argv = calls[1]["argv"]
    assert "--conversation" in second_call_argv
    conv_idx = second_call_argv.index("--conversation")
    assert second_call_argv[conv_idx + 1] == "fake-conv-uuid-123"

    # meta.json tur geçmişi kontrolü
    meta_path = test_env["state_dir"] / "tur_gorev" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["tur"] == 2
    assert len(meta["turler"]) == 1
    assert meta["turler"][0]["tur"] == 1


def test_hata_sonucu_hata_durumu(test_env: dict[str, Any]) -> None:
    """
    Model ERROR statüsü döndürdüğünde durumun 'hata' olduğunu test eder.
    """
    env = test_env["env"]
    env["FAKE_AGY_MODE"] = "error"

    res = run_ajan(
        ["baslat", "hata_gorev", "-m", "Hata verecek görev", "--bekle"],
        env=env,
    )
    # bekle bitti dışındaki durumlarda 1 ile çıkar
    assert res.returncode == 1

    meta_path = test_env["state_dir"] / "hata_gorev" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["durum"] == "hata"
    assert meta["hata"] is not None


def test_iptal_surec_grubunu_oldurur(test_env: dict[str, Any]) -> None:
    """
    iptal komutunun çalışan süreç grubunu öldürdüğünü ve durumu
    'iptal' yaptığını test eder.
    """
    env = test_env["env"]
    env["FAKE_AGY_MODE"] = "sleep"

    run_ajan(["baslat", "iptal_gorev", "-m", "Uzun iş"], env=env)
    time.sleep(0.6)

    meta_path = test_env["state_dir"] / "iptal_gorev" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pid = meta.get("pid")
    assert pid is not None
    assert is_pid_alive(pid)

    res_iptal = run_ajan(["iptal", "iptal_gorev"], env=env)
    assert res_iptal.returncode == 0

    time.sleep(0.3)
    assert not is_pid_alive(pid)

    meta_after = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_after["durum"] == "iptal"


def test_pid_olu_kayip_durumu(test_env: dict[str, Any]) -> None:
    """
    Durumu 'calisiyor' görünen ancak PID'si ölü olan görevlerin
    'kayip' olarak raporlandığını test eder.
    """
    env = test_env["env"]
    state_dir = test_env["state_dir"]

    # Sahte bir görev dizini oluştur
    dead_task_dir = state_dir / "olu_gorev"
    dead_task_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "etiket": "olu_gorev",
        "durum": "calisiyor",
        "pid": 99999999,  # Kesinlikle var olmayan PID
        "tur": 1,
        "sure_s": 5.0,
        "yazilan_dosyalar": [],
        "token_toplami": {"total_tokens": 10},
    }
    (dead_task_dir / "meta.json").write_text(
        json.dumps(meta), encoding="utf-8"
    )

    # durum tablosu kontrolü
    res = run_ajan(["durum", "olu_gorev", "--json"], env=env)
    assert res.returncode == 0
    data = json.loads(res.stdout)
    assert data["durum"] == "kayip"

    # bekle kontrolü: kayip görev için 1 döner
    res_bekle = run_ajan(["bekle", "olu_gorev"], env=env)
    assert res_bekle.returncode == 1
    assert "kayip" in res_bekle.stdout


def test_model_takma_adlari_cli_uzerinden(test_env: dict[str, Any]) -> None:
    """
    CLI üzerinden model takma adlarının (flash, argon vb.)
    tam id olarak agy'ye aktarıldığını test eder.
    """
    env = test_env["env"]
    log_path = test_env["log_path"]

    run_ajan(
        [
            "baslat",
            "model_gorev",
            "-m",
            "Model testi",
            "--model",
            "argon",
            "--bekle",
        ],
        env=env,
    )

    with open(log_path, "r", encoding="utf-8") as f:
        calls = [json.loads(line) for line in f if line.strip()]

    assert len(calls) >= 1
    argv = calls[0]["argv"]
    assert "--model" in argv
    m_idx = argv.index("--model")
    assert argv[m_idx + 1] == "gemini-4-argon-high"


def test_yazilan_dosya_yolu_cikarimi_akista(test_env: dict[str, Any]) -> None:
    """
    Canlı akışta farklı parametre anahtarlarıyla gelen yazma araçlarının
    meta['yazilan_dosyalar'] listesine eksiksiz toplandığını test eder.
    """
    env = test_env["env"]
    env["FAKE_AGY_MODE"] = "varied_keys"

    res = run_ajan(
        ["baslat", "farkli_anahtar_gorev", "-m", "Anahtar testi", "--bekle"],
        env=env,
    )
    assert res.returncode == 0

    meta_path = test_env["state_dir"] / "farkli_anahtar_gorev" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    yazilanlar = meta["yazilan_dosyalar"]

    assert "/workspace/path1.py" in yazilanlar
    assert "/workspace/target2.py" in yazilanlar
    assert "/workspace/abs3.py" in yazilanlar
    assert "/workspace/path4.py" in yazilanlar
    assert "/workspace/filepath5.py" in yazilanlar
    assert "/workspace/custom6.py" in yazilanlar

    komutlar = meta["calistirilan_komutlar"]
    assert "pytest -v" in komutlar


def test_izin_kontrol_tek_basina(test_env: dict[str, Any]) -> None:
    """
    'ajan izin kontrol' alt komutunun bağımsız çalışmasını test eder.
    """
    env = test_env["env"]

    # 1. İzin yokken çıkış 2
    res1 = run_ajan(
        ["izin", "kontrol", "--yaz", "/tmp/dizin_a", "--komut", "pytest"],
        env=env,
    )
    assert res1.returncode == 2

    # 2. İzin eklendikten sonra çıkış 0
    res2 = run_ajan(
        [
            "izin",
            "kontrol",
            "--yaz",
            "/tmp/dizin_a",
            "--komut",
            "pytest",
            "--izin-ekle",
        ],
        env=env,
    )
    assert res2.returncode == 0

    # 3. Artık mevcut olduğu için tekrar çıkış 0
    res3 = run_ajan(
        ["izin", "kontrol", "--yaz", "/tmp/dizin_a", "--komut", "pytest"],
        env=env,
    )
    assert res3.returncode == 0
    assert "Tüm izinler mevcut." in res3.stdout


# ---------------------------------------------------------------------------
# Doğrulama (dogrula) Testleri
# ---------------------------------------------------------------------------
def test_extract_dogrulama_ozet() -> None:
    """extract_dogrulama_ozet fonksiyonunun hata satırlarını doğru yakaladığını test eder."""
    text1 = """
    running test...
    FAILED test_a.py::test_1 - AssertionError
    passed test_b.py
    ERROR: module not found
    """
    ozet1 = extract_dogrulama_ozet(text1)
    assert "FAILED test_a.py" in ozet1
    assert "ERROR: module not found" in ozet1

    # Hata anahtar kelimesi içermeyen çıktı
    text2 = "Compiling project\nBuild failed with exit code 1"
    ozet2 = extract_dogrulama_ozet(text2)
    assert "Build failed with exit code 1" in ozet2


def test_dogrula_ilk_denemede_gecen(test_env: dict[str, Any]) -> None:
    """İlk denemede başarılı olan doğrulama testini doğrular."""
    env = test_env["env"]
    res_baslat = run_ajan(
        ["baslat", "dogrula_gecen", "-m", "İlk iş", "--bekle"], env=env
    )
    assert res_baslat.returncode == 0

    res_dogrula = run_ajan(
        [
            "dogrula",
            "dogrula_gecen",
            "--test",
            f"{sys.executable} -c 'exit(0)'",
        ],
        env=env,
    )
    assert res_dogrula.returncode == 0
    assert "DOGRULANDI" in res_dogrula.stdout

    meta_path = test_env["state_dir"] / "dogrula_gecen" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert len(meta.get("dogrulama", [])) == 1
    assert meta["dogrulama"][0]["tur"] == 1
    assert meta["dogrulama"][0]["cikis"] == 0

    res_durum = run_ajan(["durum", "dogrula_gecen", "--json"], env=env)
    assert res_durum.returncode == 0
    assert json.loads(res_durum.stdout)["dogrulama"] == "✓"


def test_dogrula_bir_turda_duzelen(
    test_env: dict[str, Any], tmp_path: Any
) -> None:
    """İlk turda başarısız olup takip turunda düzelen görevi doğrular."""
    env = test_env["env"]
    env["FAKE_AGY_MODE"] = "fix_on_second_turn"
    fix_file = tmp_path / "duzeltildi.txt"
    env["FAKE_AGY_FIX_FILE"] = str(fix_file)

    res_baslat = run_ajan(
        ["baslat", "dogrula_duzelen", "-m", "Düzeltme görevi", "--bekle"],
        env=env,
    )
    assert res_baslat.returncode == 0
    assert not fix_file.exists()

    test_cmd = (
        f"{sys.executable} -c \""
        f"import os, sys; "
        f"sys.exit(0 if os.path.exists({repr(str(fix_file))}) else 1)\""
    )
    res_dogrula = run_ajan(
        ["dogrula", "dogrula_duzelen", "--test", test_cmd, "--tur", "3"],
        env=env,
    )
    assert res_dogrula.returncode == 0
    assert "DOGRULANDI" in res_dogrula.stdout
    assert fix_file.is_file()

    meta_path = test_env["state_dir"] / "dogrula_duzelen" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert len(meta.get("dogrulama", [])) == 2
    assert meta["dogrulama"][0]["tur"] == 1
    assert meta["dogrulama"][0]["cikis"] == 1
    assert meta["dogrulama"][1]["tur"] == 2
    assert meta["dogrulama"][1]["cikis"] == 0
    assert meta["tur"] == 2

    res_durum = run_ajan(["durum", "dogrula_duzelen", "--json"], env=env)
    assert res_durum.returncode == 0
    assert json.loads(res_durum.stdout)["dogrulama"] == "✓"


def test_dogrula_tur_sinirinda_basarisiz(test_env: dict[str, Any]) -> None:
    """Belirtilen maksimum düzeltme turu sayısına ulaşılınca (N+1 test çalıştırması) başarısız sonlandığını doğrular."""
    env = test_env["env"]
    res_baslat = run_ajan(
        ["baslat", "dogrula_sinir", "-m", "Sınır testi", "--bekle"], env=env
    )
    assert res_baslat.returncode == 0

    test_cmd = (
        f"{sys.executable} -c \""
        f"import sys; "
        f"sys.stderr.write('FAILED test_ornek - AssertionError\\n'); "
        f"sys.exit(1)\""
    )
    res_dogrula = run_ajan(
        ["dogrula", "dogrula_sinir", "--test", test_cmd, "--tur", "2"],
        env=env,
    )
    assert res_dogrula.returncode == 1
    assert "DOGRULANAMADI (2 tur)" in res_dogrula.stdout

    meta_path = test_env["state_dir"] / "dogrula_sinir" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert len(meta.get("dogrulama", [])) == 3
    assert meta["dogrulama"][0]["cikis"] == 1
    assert meta["dogrulama"][1]["cikis"] == 1
    assert meta["dogrulama"][2]["cikis"] == 1
    assert meta["tur"] == 3
    assert "FAILED" in meta["dogrulama"][0]["ozet"]

    res_durum = run_ajan(["durum", "dogrula_sinir", "--json"], env=env)
    assert res_durum.returncode == 0
    assert json.loads(res_durum.stdout)["dogrulama"] == "✗"


def test_dogrula_calisan_gorevde_ret(test_env: dict[str, Any]) -> None:
    """Canlı çalışan bir görev üzerinde doğrulamanın reddedildiğini test eder."""
    env = test_env["env"]
    env["FAKE_AGY_MODE"] = "sleep"

    res_baslat = run_ajan(
        ["baslat", "dogrula_uyuyan", "-m", "Uzun iş"], env=env
    )
    assert res_baslat.returncode == 0
    time.sleep(0.6)

    res_dogrula = run_ajan(
        [
            "dogrula",
            "dogrula_uyuyan",
            "--test",
            f"{sys.executable} -c 'exit(0)'",
        ],
        env=env,
    )
    assert res_dogrula.returncode != 0
    assert (
        "çalışıyor" in res_dogrula.stderr.lower()
        or "bitmemiş" in res_dogrula.stderr.lower()
    )

    run_ajan(["iptal", "dogrula_uyuyan"], env=env)


def test_devam_iki_tur_sure_birinciden_bagimsiz(
    test_env: dict[str, Any]
) -> None:
    """
    Devam turlarında 'sure_s' değerinin birinci turun başlangıcından
    bağımsız olduğunu, her turun kendi başlangıç zamanını kaydettiğini
    ve toplam_sure_s değerinin doğru hesaplandığını doğrular.
    """
    env = test_env["env"]
    env["FAKE_AGY_MODE"] = "cumulative_duration"

    # 1. Tur başlat
    res1 = run_ajan(
        ["baslat", "sure_test_gorev", "-m", "1. Tur", "--bekle"], env=env
    )
    assert res1.returncode == 0

    meta_path = test_env["state_dir"] / "sure_test_gorev" / "meta.json"
    meta1 = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta1["tur"] == 1
    assert meta1["sure_s"] == 2.5
    assert meta1["toplam_sure_s"] == 2.5
    baslangic_1 = meta1.get("baslangic_zamani")
    assert baslangic_1 is not None

    # 2. Tur (devam) başlat
    res2 = run_ajan(
        ["devam", "sure_test_gorev", "-m", "2. Tur Takip", "--bekle"], env=env
    )
    assert res2.returncode == 0

    meta2 = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta2["tur"] == 2
    # 1. turun bilgileri turler listesinde saklanmalı
    assert len(meta2["turler"]) == 1
    tur1_kayit = meta2["turler"][0]
    assert tur1_kayit["tur"] == 1
    assert tur1_kayit["baslangic"] == baslangic_1
    assert tur1_kayit["sure_s"] == 2.5

    # 2. turun süresi agy'nin kümülatif 25584 değerinden bağımsız olmalı (elapsed olmalı)
    assert meta2["sure_s"] != 25584.0
    assert meta2["sure_s"] < 100.0
    assert meta2["baslangic_zamani"] is not None
    # toplam_sure_s her iki turun toplamı olmalı
    assert meta2["toplam_sure_s"] == round(
        tur1_kayit["sure_s"] + meta2["sure_s"], 2
    )
    assert meta2["toplam_sure_s"] < 25584.0

    # durum tablosunda SÜRE son turun süresi olmalı
    res_durum = run_ajan(["durum", "sure_test_gorev", "--json"], env=env)
    assert res_durum.returncode == 0
    data = json.loads(res_durum.stdout)
    assert data["sure"] == meta2["sure_s"]
    assert data["toplam_sure"] == meta2["toplam_sure_s"]


def test_extract_rapor_ingilizce_anahtarlar() -> None:
    """extract_rapor'un İngilizce anahtarlarla gelen JSON'ı da başarıyla çıkardığını test eder."""
    text = """
    Work finished.
    ```json
    {
        "summary": "Implemented feature cleanly",
        "changed_files": ["module.py"],
        "executed_tests": ["pytest: passed"],
        "open_issues": ["none"],
        "success": true
    }
    ```
    """
    r = extract_rapor(text, ["fallback.py"], ["test"])
    assert r["basarili"] is True
    assert r["ozet"] == "Implemented feature cleanly"
    assert r["degisen_dosyalar"] == ["module.py"]
    assert r["calistirilan_testler"] == ["pytest: passed"]
    assert r["acik_konular"] == ["none"]


def test_xdg_ve_ortam_degiskeni_onceligi(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """AJAN_DIZIN, XDG_STATE_HOME ve AJAN_AYAR önceliklerini doğrular."""
    custom_state = tmp_path / "custom_state"
    xdg_state = tmp_path / "xdg_home"
    custom_ayar = tmp_path / "custom_settings.json"

    # 1. AJAN_DIZIN önceliği
    monkeypatch.setenv("AJAN_DIZIN", str(custom_state))
    monkeypatch.setenv("XDG_STATE_HOME", str(xdg_state))
    assert get_state_root() == str(custom_state.resolve())

    # 2. XDG_STATE_HOME fallback
    monkeypatch.delenv("AJAN_DIZIN", raising=False)
    assert get_state_root() == str((xdg_state / "ajan").resolve())

    # 3. Varsayılan ~/.local/state/ajan
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    assert get_state_root() == os.path.abspath(
        os.path.expanduser("~/.local/state/ajan")
    )

    # 4. AJAN_AYAR önceliği
    monkeypatch.setenv("AJAN_AYAR", str(custom_ayar))
    assert get_settings_path() == str(custom_ayar.resolve())

    # 5. Varsayılan settings.json
    monkeypatch.delenv("AJAN_AYAR", raising=False)
    assert get_settings_path() == os.path.abspath(
        os.path.expanduser("~/.gemini/antigravity-cli/settings.json")
    )


def test_ajan_dil_ingilizce_hata_ve_rapor(test_env: dict[str, Any]) -> None:
    """AJAN_DIL=en iken hata, bekleme, durum ve rapor iletilerinin İngilizce çıktığını test eder."""
    env = dict(test_env["env"])
    env["AJAN_DIL"] = "en"

    # 1. Eksik izin hata mesajı (ajan tarafından üretilen hata ve çıkış kodu 2)
    res_err = run_ajan(
        ["baslat", "en_izin_hata", "-m", "Test", "--yaz", "/unauthorized/test/dir"],
        env=env,
    )
    assert res_err.returncode == 2
    assert "Error: Missing permissions in settings.json:" in res_err.stderr
    assert "write_file(/unauthorized/test/dir)" in res_err.stderr
    assert "Use '--izin-ekle' flag to automatically add permissions." in res_err.stderr

    # 2. Görev dosyası bulunamadı hata mesajı (ajan tarafından üretilen hata ve çıkış kodu 1)
    res_file_err = run_ajan(
        ["baslat", "en_dosya_hata", "-g", "/nonexistent/path/task.md"],
        env=env,
    )
    assert res_file_err.returncode == 1
    assert "Error: Task file not found: /nonexistent/path/task.md" in res_file_err.stderr

    # 3. Başlatma ve bekleme
    res_ok = run_ajan(
        ["baslat", "en_gorev", "-m", "English task", "--bekle"], env=env
    )
    assert res_ok.returncode == 0
    assert "completed" in res_ok.stdout

    # 4. Rapor formatı
    res_rapor = run_ajan(["rapor", "en_gorev"], env=env)
    assert res_rapor.returncode == 0
    assert "=== Task Report: en_gorev ===" in res_rapor.stdout
    assert "Successful: Yes" in res_rapor.stdout
    assert "Summary:" in res_rapor.stdout

    # 5. Durum tablosu başlıkları
    res_durum = run_ajan(["durum", "en_gorev"], env=env)
    assert res_durum.returncode == 0
    assert "TAG" in res_durum.stdout
    assert "STATUS" in res_durum.stdout


def test_izin_ekle_bozuk_settings_uzerine_yazmaz(test_env: dict[str, Any]) -> None:
    """
    settings.json geçerli JSON değilse --izin-ekle dosyayı ezmemeli,
    hata vermeli ve görevi başlatmamalıdır.
    """
    env = test_env["env"]
    settings_path = test_env["settings_path"]
    bozuk = '{\n  // yorum satırı\n  "model": "x",\n  "permissions": {"allow": []}\n}\n'
    settings_path.write_text(bozuk, encoding="utf-8")

    res = run_ajan(
        [
            "baslat",
            "bozuk_ayar_gorev",
            "-m",
            "Görev",
            "--yaz",
            "/tmp/bozuk_ayar_dizin",
            "--izin-ekle",
        ],
        env=env,
    )
    assert res.returncode != 0
    assert settings_path.read_text(encoding="utf-8") == bozuk
    assert str(settings_path) in res.stderr


def test_add_permissions_bozuk_json_hata_firlatir(tmp_path: Any) -> None:
    yol = tmp_path / "settings.json"
    yol.write_text("{bozuk", encoding="utf-8")
    with pytest.raises(ValueError):
        add_permissions(["write_file(/tmp/x)"], str(yol))
    assert yol.read_text(encoding="utf-8") == "{bozuk"


# ---------------------------------------------------------------------------
# Yeni Hata Düzeltme Testleri (Madde 1-12)
# ---------------------------------------------------------------------------
def test_gorev_dosyalari_tekrarli_g_ve_coklu_sirali(
    test_env: dict[str, Any], tmp_path: Any
) -> None:
    """-g A -g B ve -g A B iki dosyayı da sırasını koruyarak birleştirmelidir."""
    env = test_env["env"]
    f1 = tmp_path / "birinci.md"
    f2 = tmp_path / "ikinci.md"
    f3 = tmp_path / "ucuncu.md"
    f1.write_text("BIRINCI_BOLUM", encoding="utf-8")
    f2.write_text("IKINCI_BOLUM", encoding="utf-8")
    f3.write_text("UCUNCU_BOLUM", encoding="utf-8")

    # 1. Tekrarlı -g A -g B
    res1 = run_ajan(
        ["baslat", "g_tekrar", "-g", str(f1), "-g", str(f2), "--bekle"],
        env=env,
    )
    assert res1.returncode == 0, res1.stderr
    gemini1 = (test_env["state_dir"] / "g_tekrar" / "GEMINI.md").read_text(
        encoding="utf-8"
    )
    assert "BIRINCI_BOLUM" in gemini1
    assert "IKINCI_BOLUM" in gemini1
    assert gemini1.index("BIRINCI_BOLUM") < gemini1.index("IKINCI_BOLUM")

    # 2. Karma -g A B -g C
    res2 = run_ajan(
        [
            "baslat",
            "g_coklu",
            "-g",
            str(f1),
            str(f2),
            "-g",
            str(f3),
            "--bekle",
        ],
        env=env,
    )
    assert res2.returncode == 0, res2.stderr
    gemini2 = (test_env["state_dir"] / "g_coklu" / "GEMINI.md").read_text(
        encoding="utf-8"
    )
    assert (
        gemini2.index("BIRINCI_BOLUM")
        < gemini2.index("IKINCI_BOLUM")
        < gemini2.index("UCUNCU_BOLUM")
    )


def test_iptal_calismayan_gorevde_sinyal_gondermez_ve_durumu_korur(
    test_env: dict[str, Any]
) -> None:
    """cmd_iptal yalnızca durum=='calisiyor' ve canlıyken sinyal göndermeli; aksi halde çıkış 1 vermeli."""
    env = test_env["env"]
    state_dir = test_env["state_dir"]

    # Sahte canlı bir süreç başlat; bitti durumundaki meta'da yanlışlıkla bu PID dursa bile sinyal gitmemeli
    masum_proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        start_new_session=True,
    )
    try:
        for idx, (durum, p_val) in enumerate(
            [
                ("bitti", masum_proc.pid),
                ("hata", masum_proc.pid),
                ("iptal", masum_proc.pid),
                ("calisiyor", 99999999),
            ]
        ):
            etiket = f"pasif_{idx}_{durum}"
            tdir = state_dir / etiket
            tdir.mkdir(parents=True, exist_ok=True)
            meta = {
                "etiket": etiket,
                "durum": durum,
                "pid": p_val,
                "bekci_pid": None,
                "tur": 1,
            }
            (tdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

            res = run_ajan(["iptal", etiket], env=env)
            assert res.returncode == 1
            assert "görev çalışmıyor" in res.stderr.lower()
            after = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
            assert after["durum"] == durum

            # İngilizce mesaj kontrolü
            env_en = dict(env, AJAN_DIL="en")
            res_en = run_ajan(["iptal", etiket], env=env_en)
            assert res_en.returncode == 1
            assert "not running" in res_en.stderr.lower()

        # Masum süreç hala canlı olmalı
        assert masum_proc.poll() is None
    finally:
        masum_proc.terminate()
        masum_proc.wait(timeout=5)


def test_iptal_once_meta_iptal_yazar_sonra_sinyal_gonderir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """cmd_iptal sinyal göndermeden önce meta.json'a durum='iptal' yazmalıdır."""
    state_dir = tmp_path / "state"
    monkeypatch.setenv("AJAN_DIZIN", str(state_dir))
    task_dir = state_dir / "canli_iptal"
    task_dir.mkdir(parents=True, exist_ok=True)
    ajan.save_meta(
        str(task_dir),
        {
            "etiket": "canli_iptal",
            "durum": "calisiyor",
            "pid": 12345,
            "bekci_pid": 12346,
        },
    )

    observed_statuses: list[str | None] = []
    alive_calls = {"n": 0}

    def fake_alive(pid: int | None) -> bool:
        # İlk gorev_canli + iki SIGTERM kontrolünde canlı, bekleme döngüsünde ölü
        alive_calls["n"] += 1
        return alive_calls["n"] <= 3

    def fake_killpg(pgid: int, sig: int) -> None:
        m = ajan.load_meta(str(task_dir))
        observed_statuses.append(m.get("durum") if m else None)

    def fake_kill(pid: int, sig: int) -> None:
        m = ajan.load_meta(str(task_dir))
        observed_statuses.append(m.get("durum") if m else None)

    monkeypatch.setattr(ajan, "is_pid_alive", fake_alive)
    monkeypatch.setattr(os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(os, "killpg", fake_killpg)
    monkeypatch.setattr(os, "kill", fake_kill)

    args = type("Args", (), {"etiket": "canli_iptal"})()
    ajan.cmd_iptal(args)

    assert len(observed_statuses) >= 1
    assert all(st == "iptal" for st in observed_statuses)


def test_etiket_dogrulama_tum_komutlar_ve_symlink(test_env: dict[str, Any], tmp_path: Any) -> None:
    """Geçersiz etiketler ve state_root dışına kaçan yollar tr/en hata ve çıkış 1 ile reddedilmelidir."""
    env = test_env["env"]
    state_dir = test_env["state_dir"]

    invalid_labels = [
        ".",
        "..",
        "../kacis",
        "alt/dizin",
        "a\\b",
        "bosluk var",
        "türkçe",
        "",
        "x" * 65,
    ]
    commands_per_label: list[list[str]] = [
        ["baslat", "{lbl}", "-m", "test"],
        ["devam", "{lbl}", "-m", "takip"],
        ["dogrula", "{lbl}", "--test", "true"],
        ["durum", "{lbl}"],
        ["bekle", "{lbl}"],
        ["rapor", "{lbl}"],
        ["izle", "{lbl}"],
        ["iptal", "{lbl}"],
    ]

    for lbl in invalid_labels:
        for cmd_tpl in commands_per_label:
            cmd = [c.format(lbl=lbl) for c in cmd_tpl]
            res_tr = run_ajan(cmd, env=env)
            assert res_tr.returncode == 1, f"TR geçerli saydı: {cmd}"
            assert res_tr.stderr.strip(), f"TR hata mesajı boş: {cmd}"

            env_en = dict(env, AJAN_DIL="en")
            res_en = run_ajan(cmd, env=env_en)
            assert res_en.returncode == 1, f"EN geçerli saydı: {cmd}"
            assert "Error:" in res_en.stderr, f"EN hata mesajı bekleniyordu: {cmd}"

    # Symlink ile state_root dışına kaçış denemesi
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "kacis_link").symlink_to(outside_dir)
    res_sym = run_ajan(["baslat", "kacis_link", "-m", "deneme"], env=env)
    assert res_sym.returncode == 1
    assert res_sym.stderr.strip()

    # Geçerli sınır etiketleri (64 karakter, nokta/tire/altçizgi) çalışmalı
    valid_lbl = "A1_b-2." + ("z" * 57)
    assert len(valid_lbl) == 64
    res_ok = run_ajan(["baslat", valid_lbl, "-m", "geçerli", "--bekle"], env=env)
    assert res_ok.returncode == 0, res_ok.stderr


def test_meta_yarisi_gecici_dosya_ve_bekci_pid_koruma(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, fake_agy: tuple[str, str]
) -> None:
    """
    (a) save_meta benzersiz geçici dosya kullanmalı.
    (b) cmd_baslat ve calistir_devam bekçi başlatıldıktan sonra meta.json'u yeniden okuyup
        yalnız bekci_pid'i güncellemeli; calistir_devam pid=None atamasını bekçiden önce yapmalı.
    """
    fake_bin, _ = fake_agy
    state_dir = tmp_path / "state"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"permissions": {"allow": []}}), encoding="utf-8")
    monkeypatch.setenv("AJAN_DIZIN", str(state_dir))
    monkeypatch.setenv("AJAN_AYAR", str(settings_path))
    monkeypatch.setenv("AJAN_AGY", fake_bin)

    # (a) os.replace'e verilen geçici dosya meta.json.tmp değil, benzersiz olmalı
    tmp_sources: list[str] = []
    orig_replace = os.replace

    def spy_replace(src: str, dst: str) -> None:
        tmp_sources.append(os.path.basename(src))
        orig_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy_replace)
    tdir_tmp = tmp_path / "save_test"
    ajan.save_meta(str(tdir_tmp), {"a": 1})
    ajan.save_meta(str(tdir_tmp), {"a": 2})
    assert len(tmp_sources) == 2
    assert all(s != "meta.json.tmp" for s in tmp_sources)
    assert tmp_sources[0] != tmp_sources[1]
    assert all(str(os.getpid()) in s for s in tmp_sources)
    monkeypatch.undo()
    monkeypatch.setenv("AJAN_DIZIN", str(state_dir))
    monkeypatch.setenv("AJAN_AYAR", str(settings_path))
    monkeypatch.setenv("AJAN_AGY", fake_bin)

    # (b1) cmd_baslat testi
    class FakeProc:
        def __init__(self, pid: int) -> None:
            self.pid = pid

    def fake_popen_baslat(*args: Any, **kwargs: Any) -> FakeProc:
        # Bekçi başlatılır başlamaz pid ve baslangic_zamani yazmış gibi davran
        tdir = state_dir / "yaris_baslat"
        m = ajan.load_meta(str(tdir))
        assert m is not None
        m["pid"] = 77777
        m["baslangic_zamani"] = "2099-05-05T12:00:00"
        ajan.save_meta(str(tdir), m)
        return FakeProc(88888)

    monkeypatch.setattr(subprocess, "Popen", fake_popen_baslat)
    baslat_args = type(
        "Args",
        (),
        {
            "etiket": "yaris_baslat",
            "gorev_dosyalari": None,
            "mesaj": "test",
            "model": "hydrogen",
            "effort": None,
            "yaz": [],
            "oku": [],
            "komut": [],
            "sure": None,
            "sandbox": False,
            "izin_ekle": False,
            "bekle": False,
        },
    )()
    with pytest.raises(SystemExit) as exc:
        ajan.cmd_baslat(baslat_args)
    assert exc.value.code == 0

    meta_b = ajan.load_meta(str(state_dir / "yaris_baslat"))
    assert meta_b is not None
    assert meta_b["pid"] == 77777
    assert meta_b["baslangic_zamani"] == "2099-05-05T12:00:00"
    assert meta_b["bekci_pid"] == 88888

    # (b2) calistir_devam testi: Popen çağrılmadan önce pid=None yazılmış olmalı,
    # Popen sırasında bekçinin yazdığı pid/baslangic_zamani korunmalı.
    meta_b["durum"] = "bitti"
    meta_b["conversation_id"] = "conv-123"
    ajan.save_meta(str(state_dir / "yaris_baslat"), meta_b)

    pid_before_popen: list[Any] = []

    def fake_popen_devam(*args: Any, **kwargs: Any) -> FakeProc:
        tdir = state_dir / "yaris_baslat"
        m = ajan.load_meta(str(tdir))
        assert m is not None
        pid_before_popen.append(m.get("pid"))
        m["pid"] = 99999
        m["baslangic_zamani"] = "2099-06-06T12:00:00"
        ajan.save_meta(str(tdir), m)
        return FakeProc(88889)

    monkeypatch.setattr(subprocess, "Popen", fake_popen_devam)
    rc = ajan.calistir_devam("yaris_baslat", "takip", bekle=False)
    assert rc == 0
    assert pid_before_popen == [None]

    meta_d = ajan.load_meta(str(state_dir / "yaris_baslat"))
    assert meta_d is not None
    assert meta_d["pid"] == 99999
    assert meta_d["baslangic_zamani"] == "2099-06-06T12:00:00"
    assert meta_d["bekci_pid"] == 88889


def test_run_bekci_hata_oncelik_sirasi(
    test_env: dict[str, Any], tmp_path: Any
) -> None:
    """
    run_bekci hata dalı öncelik sırası:
    result_status (!= SUCCESS) -> hata.log son hata -> agy çıkış kodu != 0 -> boş yanıt.
    """
    custom_agy = tmp_path / "custom_err_agy.py"
    custom_agy.write_text(
        """#!/usr/bin/env python3
import json, os, sys
case = os.environ["TEST_CASE"]
if case == "result_status":
    sys.stderr.write("ERROR: stderr mesaji\\n")
    print(json.dumps({"event": "result", "result": {"status": "FAILED_MODEL", "response": ""}}), flush=True)
    sys.exit(2)
elif case == "hata_log":
    sys.stderr.write("INFO: basladi\\n")
    sys.stderr.write("ERROR: baglanti koptu\\n")
    sys.exit(2)
elif case == "exit_code":
    sys.exit(3)
elif case == "empty_resp":
    print(json.dumps({"event": "result", "result": {"status": "SUCCESS", "response": "   "}}), flush=True)
    sys.exit(0)
""",
        encoding="utf-8",
    )
    custom_agy.chmod(custom_agy.stat().st_mode | stat.S_IEXEC)

    env = dict(test_env["env"])
    env["AJAN_AGY"] = str(custom_agy)
    state_dir = test_env["state_dir"]

    expectations = [
        ("result_status", "FAILED_MODEL"),
        ("hata_log", "ERROR: baglanti koptu"),
        ("exit_code", "agy çıkış kodu: 3"),
        ("empty_resp", "Boş yanıt döndü"),
    ]
    for case, expected_err in expectations:
        env["TEST_CASE"] = case
        res = run_ajan(["baslat", f"err_{case}", "-m", "test", "--bekle"], env=env)
        assert res.returncode == 1
        meta = json.loads((state_dir / f"err_{case}" / "meta.json").read_text(encoding="utf-8"))
        assert meta["durum"] == "hata"
        assert meta["hata"] == expected_err


def test_extract_rapor_rapor_anahtarlari_dogrulamasi() -> None:
    """
    extract_rapor yalnız rapor anahtarlarından en az birini içeren JSON sözlüğünü rapor saymalı,
    aksi halde önceki adaya geçmeli veya fallback (basarili: None) üretmelidir.
    """
    # 1. Sonda ilgisiz JSON bloğu varsa önceki geçerli rapor bloğunu seçmeli
    text_with_trailing_other = """
    ```json
    {"ozet": "Asıl rapor", "degisen_dosyalar": ["x.py"], "basarili": true}
    ```
    Örnek config:
    ```json
    {"port": 8080, "debug": true}
    ```
    """
    r1 = extract_rapor(text_with_trailing_other, ["y.py"], [])
    assert r1["ozet"] == "Asıl rapor"
    assert r1["degisen_dosyalar"] == ["x.py"]
    assert r1["basarili"] is True

    # 2. Yalnızca ilgisiz JSON bloğu varsa rapor sayılmamalı -> fallback (basarili: None)
    text_only_other = """
    İşlem yapıldı.
    ```json
    {"status": "ok", "count": 5}
    ```
    """
    r2 = extract_rapor(text_only_other, ["z.py"], ["pytest"])
    assert r2["basarili"] is None
    assert r2["degisen_dosyalar"] == ["z.py"]
    assert r2["calistirilan_testler"] == ["pytest"]

    # 3. İzin verilen anahtarlardan herhangi biri (ör. acik_konular veya open_issues) varsa rapor sayılmalı
    r3 = extract_rapor('```json\n{"open_issues": ["kalan iş"]}\n```', [], [])
    assert r3["acik_konular"] == ["kalan iş"]
    assert r3["basarili"] is True


def test_temizle_yalniz_okunabilen_meta_icerenleri_siler(
    test_env: dict[str, Any]
) -> None:
    """cmd_temizle yalnızca load_meta ile okunabilen meta.json içeren eski dizinleri silmelidir."""
    env = test_env["env"]
    state_dir = test_env["state_dir"]
    old_ts = time.time() - (10 * 86400)

    # 1. Geçerli eski görev -> silinmeli
    valid_dir = state_dir / "eski_gorev"
    valid_dir.mkdir(parents=True, exist_ok=True)
    (valid_dir / "meta.json").write_text(
        json.dumps({"etiket": "eski_gorev", "durum": "bitti"}), encoding="utf-8"
    )
    os.utime(valid_dir, (old_ts, old_ts))

    # 2. meta.json olmayan yabancı dizin -> dokunulmamalı
    unrelated_dir = state_dir / "yabanci_dizin"
    unrelated_dir.mkdir(parents=True, exist_ok=True)
    (unrelated_dir / "not.txt").write_text("önemli", encoding="utf-8")
    os.utime(unrelated_dir, (old_ts, old_ts))

    # 3. Bozuk meta.json içeren dizin -> dokunulmamalı
    corrupt_dir = state_dir / "bozuk_meta_dizin"
    corrupt_dir.mkdir(parents=True, exist_ok=True)
    (corrupt_dir / "meta.json").write_text("{bozuk json", encoding="utf-8")
    os.utime(corrupt_dir, (old_ts, old_ts))

    # 4. Canlı çalışan görev -> dokunulmamalı
    live_proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        start_new_session=True,
    )
    try:
        live_dir = state_dir / "canli_eski"
        live_dir.mkdir(parents=True, exist_ok=True)
        (live_dir / "meta.json").write_text(
            json.dumps(
                {"etiket": "canli_eski", "durum": "calisiyor", "pid": live_proc.pid}
            ),
            encoding="utf-8",
        )
        os.utime(live_dir, (old_ts, old_ts))

        res = run_ajan(["temizle", "--gun", "7"], env=env)
        assert res.returncode == 0
        assert not valid_dir.exists()
        assert unrelated_dir.exists()
        assert corrupt_dir.exists()
        assert live_dir.exists()
    finally:
        live_proc.terminate()
        live_proc.wait(timeout=5)


def test_is_pid_alive_zombi_ve_cocuk_toplama(tmp_path: Any) -> None:
    """
    is_pid_alive hem çocuk zombiyi waitpid ile toplayıp False dönmeli,
    hem de çocuk olmayan zombiyi /proc/<pid>/stat 'Z' alanından ölü saymalıdır.
    """
    # 1. Doğrudan çocuk zombi (waitpid ile toplanır)
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    # Çıkan çocuk zombi kalır; is_pid_alive onu waitpid ile toplayıp False dönmeli.
    # Toplamasaydı os.kill(pid, 0) zombide başarılı olur ve (/proc yoksa) hep True dönerdi.
    deadline = time.time() + 15.0
    while is_pid_alive(child.pid) and time.time() < deadline:
        time.sleep(0.05)
    assert is_pid_alive(child.pid) is False
    with pytest.raises(ChildProcessError):
        os.waitpid(child.pid, os.WNOHANG)  # zaten toplanmış olmalı

    # 2. Çocuk olmayan zombi: yalnız /proc/<pid>/stat ile görülebilir (Linux).
    if not os.path.exists("/proc/self/stat"):
        return
    pid_file = tmp_path / "grandchild.pid"
    parent_proc = subprocess.Popen(
        [
            sys.executable,
            "-c",
            (
                "import subprocess, sys, time; "
                "gc = subprocess.Popen([sys.executable, '-c', 'pass']); "
                f"open({repr(str(pid_file))}, 'w').write(str(gc.pid)); "
                "time.sleep(10)"
            ),
        ]
    )
    try:
        deadline = time.time() + 3.0
        while not pid_file.exists() and time.time() < deadline:
            time.sleep(0.02)
        gc_pid = int(pid_file.read_text(encoding="utf-8").strip())

        # Torunun zombi ('Z') haline gelmesini bekle
        while time.time() < deadline:
            stat_txt = open(f"/proc/{gc_pid}/stat", encoding="utf-8").read()
            rp = stat_txt.rfind(")")
            if rp != -1 and stat_txt[rp + 1 :].lstrip().startswith("Z"):
                break
            time.sleep(0.02)

        assert is_pid_alive(gc_pid) is False
    finally:
        parent_proc.terminate()
        parent_proc.wait(timeout=5)


def test_izle_surec_kayip_olunca_cikar(test_env: dict[str, Any]) -> None:
    """cmd_izle döngüde durum=='calisiyor' iken gorev_canli False ise 'süreç kayıp' iletisiyle çıkmalıdır."""
    env = test_env["env"]
    tdir = test_env["state_dir"] / "izle_kayip"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / "meta.json").write_text(
        json.dumps(
            {
                "etiket": "izle_kayip",
                "durum": "calisiyor",
                "pid": 99999999,
                "bekci_pid": None,
            }
        ),
        encoding="utf-8",
    )
    (tdir / "olaylar.jsonl").write_text(
        json.dumps({"event": "init", "init": {"model": "test"}}) + "\n",
        encoding="utf-8",
    )

    res = run_ajan(["izle", "izle_kayip"], env=env, timeout=4.0)
    assert res.returncode == 1
    assert "süreç kayıp" in (res.stdout + res.stderr).lower()


def test_dogrula_sifir_tur_ve_calistir_devam_hatasi(test_env: dict[str, Any]) -> None:
    """
    --tur 0 en fazla 1 test çalıştırıp 0 düzeltme turu yapmalı;
    calistir_devam sıfır dışı dönerse döngüden çıkıp DOGRULANAMADI yazmalıdır.
    """
    env = test_env["env"]

    # 1. --tur 0 -> 1 test çalıştırması, 0 düzeltme
    res_b1 = run_ajan(["baslat", "dogrula_0", "-m", "iş", "--bekle"], env=env)
    assert res_b1.returncode == 0
    res_d0 = run_ajan(
        ["dogrula", "dogrula_0", "--test", f"{sys.executable} -c 'exit(1)'", "--tur", "0"],
        env=env,
    )
    assert res_d0.returncode == 1
    assert "DOGRULANAMADI" in res_d0.stdout
    meta0 = json.loads((test_env["state_dir"] / "dogrula_0" / "meta.json").read_text(encoding="utf-8"))
    assert len(meta0["dogrulama"]) == 1
    assert meta0["tur"] == 1

    # 2. calistir_devam sıfır dışı döndüğünde (ör. error modu) döngü devam etmemeli
    res_b2 = run_ajan(["baslat", "dogrula_devam_err", "-m", "iş", "--bekle"], env=env)
    assert res_b2.returncode == 0

    env_err = dict(env, FAKE_AGY_MODE="error")
    res_d_err = run_ajan(
        [
            "dogrula",
            "dogrula_devam_err",
            "--test",
            f"{sys.executable} -c 'exit(1)'",
            "--tur",
            "3",
        ],
        env=env_err,
    )
    assert res_d_err.returncode == 1
    assert "DOGRULANAMADI" in res_d_err.stdout
    meta_err = json.loads(
        (test_env["state_dir"] / "dogrula_devam_err" / "meta.json").read_text(encoding="utf-8")
    )
    # İlk test başarısız oldu -> 1. düzeltme calistir_devam hata döndü -> döngüden çıktı (yalnız 1 test kaydı)
    assert len(meta_err["dogrulama"]) == 1

    # 3. --tur yardım metni N+1 açıklaması içermeli
    res_help = run_ajan(["dogrula", "--help"], env=env)
    assert res_help.returncode == 0
    assert "N+1" in res_help.stdout


def test_wait_for_tasks_iptal_yazim_yarisi_tekrar_okur(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
) -> None:
    """
    wait_for_tasks durum=='calisiyor' ve süreç ölü iken 'kayip' demeden önce
    meta.json'u bir kez daha okuyup değişmiş durumu (ör. 'iptal') raporlamalıdır.
    """
    state_dir = tmp_path / "state"
    monkeypatch.setenv("AJAN_DIZIN", str(state_dir))
    tdir = state_dir / "yaris_bekle"
    tdir.mkdir(parents=True, exist_ok=True)
    meta = {
        "etiket": "yaris_bekle",
        "durum": "calisiyor",
        "pid": 99999999,
        "bekci_pid": None,
        "tur": 1,
        "sure_s": 1.0,
        "yazilan_dosyalar": [],
    }
    ajan.save_meta(str(tdir), meta)

    def racing_gorev_canli(m: dict[str, Any] | None) -> bool:
        # Yarışı simüle et: gorev_canli False dönmeden az önce iptal meta'ya yazılmış olsun
        updated = dict(m or {})
        updated["durum"] = "iptal"
        ajan.save_meta(str(tdir), updated)
        return False

    monkeypatch.setattr(ajan, "gorev_canli", racing_gorev_canli)
    rc = ajan.wait_for_tasks(["yaris_bekle"], zaman_asimi=2.0)
    out = capsys.readouterr().out
    assert rc == 1
    assert "iptal" in out.lower()
    assert "kayip" not in out.lower()


def test_varsayilan_model_cli_uzerinden_neon(test_env: dict[str, Any]) -> None:
    """--model verilmediğinde agy CLI'a varsayılan gemini-4-neon-xhigh aktarılmalıdır."""
    env = test_env["env"]
    res = run_ajan(["baslat", "varsayilan_model", "-m", "test", "--bekle"], env=env)
    assert res.returncode == 0
    calls = [
        json.loads(line)
        for line in open(test_env["log_path"], encoding="utf-8")
        if line.strip()
    ]
    argv = calls[0]["argv"]
    m_idx = argv.index("--model")
    assert argv[m_idx + 1] == "gemini-4-neon-xhigh"


# ---------------------------------------------------------------------------
# Görev C: agy Hata Ayrıntısı, İngilizce Komut/Bayraklar ve SKILL.md
# ---------------------------------------------------------------------------
def test_result_error_ayrintisi_hata_log_ve_invalid_model_ipucu(
    test_env: dict[str, Any], tmp_path: Any
) -> None:
    """
    result olayındaki 'error' alanı meta['hata']'ya '<status>: <ilk satır>' olarak yazılmalı,
    tam metin hata.log'a eklenmeli ve 'invalid model' içeren hatalarda bekle/rapor çıktısında
    TR/EN model ipucu gösterilmelidir.
    """
    custom_agy = tmp_path / "model_err_agy.py"
    custom_agy.write_text(
        """#!/usr/bin/env python3
import json, os, sys
case = os.environ.get("ERR_CASE", "invalid_model")
print(json.dumps({"event": "init", "conversation_id": "conv-err-1", "init": {"model": "x"}}), flush=True)
if case == "invalid_model":
    err_text = (
        'invalid model selection (--model "x" ...): model x is not recognized\\n'
        "Available models:\\n"
        "  gemini-4-hydrogen-xhigh\\n"
        "  gemini-3.8-flash-high"
    )
    print(json.dumps({"event": "result", "result": {"conversation_id": "conv-err-1", "status": "ERROR", "error": err_text}}), flush=True)
    sys.exit(1)
elif case == "other_error":
    err_text = "quota exceeded for project\\nRetry after 60s"
    print(json.dumps({"event": "result", "result": {"conversation_id": "conv-err-1", "status": "ERROR", "error": err_text}}), flush=True)
    sys.exit(1)
""",
        encoding="utf-8",
    )
    custom_agy.chmod(custom_agy.stat().st_mode | stat.S_IEXEC)

    env = dict(test_env["env"])
    env["AJAN_AGY"] = str(custom_agy)
    state_dir = test_env["state_dir"]

    # 1. Geçersiz model hatası: meta['hata'], hata.log ve TR ipucu
    env["ERR_CASE"] = "invalid_model"
    res_tr = run_ajan(
        ["baslat", "gecersiz_model", "-m", "test", "--model", "x", "--bekle"],
        env=env,
    )
    assert res_tr.returncode == 1

    tdir = state_dir / "gecersiz_model"
    meta = json.loads((tdir / "meta.json").read_text(encoding="utf-8"))
    assert meta["durum"] == "hata"
    assert meta["hata"] == 'ERROR: invalid model selection (--model "x" ...): model x is not recognized'

    hata_log = (tdir / "hata.log").read_text(encoding="utf-8")
    assert "Available models:" in hata_log
    assert "gemini-3.8-flash-high" in hata_log

    tr_hint = "Kullanılabilir modelleri görmek için: agy models; farklı model için --model"
    en_hint = "Run 'agy models' to list available models; choose one with --model"

    assert tr_hint in res_tr.stdout

    res_bekle = run_ajan(["bekle", "gecersiz_model"], env=env)
    assert res_bekle.returncode == 1
    assert tr_hint in res_bekle.stdout

    res_rapor = run_ajan(["rapor", "gecersiz_model"], env=env)
    assert res_rapor.returncode == 0
    assert tr_hint in res_rapor.stdout

    # 2. İngilizce ipucu (AJAN_DIL=en)
    env_en = dict(env, AJAN_DIL="en")
    res_wait_en = run_ajan(["wait", "gecersiz_model"], env=env_en)
    assert res_wait_en.returncode == 1
    assert en_hint in res_wait_en.stdout

    res_report_en = run_ajan(["report", "gecersiz_model"], env=env_en)
    assert res_report_en.returncode == 0
    assert en_hint in res_report_en.stdout

    # 3. Model dışı hata: yine ilk satır meta['hata'] ve tam metin hata.log'da, ancak model ipucu yok
    env["ERR_CASE"] = "other_error"
    res_other = run_ajan(
        ["baslat", "baska_hata", "-m", "test", "--bekle"], env=env
    )
    assert res_other.returncode == 1
    tdir2 = state_dir / "baska_hata"
    meta2 = json.loads((tdir2 / "meta.json").read_text(encoding="utf-8"))
    assert meta2["hata"] == "ERROR: quota exceeded for project"
    assert "Retry after 60s" in (tdir2 / "hata.log").read_text(encoding="utf-8")
    assert tr_hint not in res_other.stdout
    res_rapor2 = run_ajan(["rapor", "baska_hata"], env=env)
    assert tr_hint not in res_rapor2.stdout


def test_ingilizce_alt_komutlar_ve_bayrak_esdegerleri(
    test_env: dict[str, Any], tmp_path: Any
) -> None:
    """
    İngilizce alt komut takma adları ve bayrak eşdeğerlerinin sahte agy üzerinde
    uçtan uca çalıştığını doğrular.
    """
    env = dict(test_env["env"])
    state_dir = test_env["state_dir"]
    log_path = test_env["log_path"]
    settings_path = test_env["settings_path"]

    write_dir = tmp_path / "en_write_dir"
    read_dir = tmp_path / "en_read_dir"
    write_dir.mkdir(parents=True, exist_ok=True)
    read_dir.mkdir(parents=True, exist_ok=True)

    # 1. perms check --write (izin yokken çıkış 2)
    res_perm_missing = run_ajan(
        ["perms", "check", "--write", str(write_dir)], env=env
    )
    assert res_perm_missing.returncode == 2
    assert f"write_file({write_dir.resolve()})" in res_perm_missing.stderr

    # 2. perms check --write --allow-cmd --add-perms
    res_perm_add = run_ajan(
        [
            "perms",
            "check",
            "--write",
            str(write_dir),
            "--allow-cmd",
            "pytest -q",
            "--add-perms",
        ],
        env=env,
    )
    assert res_perm_add.returncode == 0
    settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
    assert f"write_file({write_dir.resolve()})" in settings_data["permissions"]["allow"]
    assert "command(pytest -q)" in settings_data["permissions"]["allow"]

    # 3. start + --message + --write + --wait
    res_start = run_ajan(
        [
            "start",
            "en_task_1",
            "--message",
            "Implement feature in English",
            "--write",
            str(write_dir),
            "--read",
            str(read_dir),
            "--allow-cmd",
            "pytest -q",
            "--max-time",
            "10m",
            "--wait",
        ],
        env=env,
    )
    assert res_start.returncode == 0, res_start.stderr

    meta1 = json.loads((state_dir / "en_task_1" / "meta.json").read_text(encoding="utf-8"))
    assert meta1["durum"] == "bitti"
    assert meta1["sure"] == "10m"
    assert str(write_dir.resolve()) in meta1["yaz"]
    assert str(read_dir.resolve()) in meta1["oku"]
    assert "pytest -q" in meta1["komut"]

    calls = [json.loads(line) for line in open(log_path, encoding="utf-8") if line.strip()]
    assert "--print-timeout" in calls[0]["argv"]
    assert calls[0]["argv"][calls[0]["argv"].index("--print-timeout") + 1] == "10m"

    # 4. status
    res_status = run_ajan(["status", "en_task_1", "--json"], env=env)
    assert res_status.returncode == 0
    assert json.loads(res_status.stdout)["durum"] == "bitti"

    # 5. report ve report --raw
    res_report = run_ajan(["report", "en_task_1"], env=env)
    assert res_report.returncode == 0
    assert "Sonuç başarılı." in res_report.stdout

    res_report_raw = run_ajan(["report", "en_task_1", "--raw"], env=env)
    assert res_report_raw.returncode == 0
    assert "Görev tamamlandı." in res_report_raw.stdout

    # 6. continue + --message + --wait
    res_cont = run_ajan(
        ["continue", "en_task_1", "--message", "Follow up", "--wait"], env=env
    )
    assert res_cont.returncode == 0, res_cont.stderr
    meta1_after = json.loads((state_dir / "en_task_1" / "meta.json").read_text(encoding="utf-8"))
    assert meta1_after["tur"] == 2

    # 7. verify --rounds (hem geçen hem kalan)
    res_verify_ok = run_ajan(
        [
            "verify",
            "en_task_1",
            "--test",
            f"{sys.executable} -c 'exit(0)'",
            "--rounds",
            "1",
            "--timeout",
            "5",
        ],
        env=env,
    )
    assert res_verify_ok.returncode == 0
    assert "DOGRULANDI" in res_verify_ok.stdout

    res_verify_fail = run_ajan(
        [
            "verify",
            "en_task_1",
            "--test",
            f"{sys.executable} -c 'exit(1)'",
            "--rounds",
            "1",
        ],
        env=env,
    )
    assert res_verify_fail.returncode == 1
    assert "DOGRULANAMADI (1 tur)" in res_verify_fail.stdout

    # 8. watch (bitmiş görevde olayları okuyup çıkar)
    res_watch = run_ajan(["watch", "en_task_1"], env=env, timeout=4.0)
    assert res_watch.returncode == 0
    assert "BAŞLANGIÇ" in res_watch.stdout

    # 9. start --task-files --wait
    task_file = tmp_path / "en_task.md"
    task_file.write_text("TASK_FROM_FILE_EN", encoding="utf-8")
    res_tf = run_ajan(
        ["start", "en_task_file", "--task-files", str(task_file), "--wait"],
        env=env,
    )
    assert res_tf.returncode == 0
    assert "TASK_FROM_FILE_EN" in (state_dir / "en_task_file" / "GEMINI.md").read_text(
        encoding="utf-8"
    )

    # 10. wait --timeout ve cancel (uyuyan görevde)
    env_sleep = dict(env, FAKE_AGY_MODE="sleep")
    res_sleep = run_ajan(
        ["start", "en_sleep_task", "--message", "Sleep"], env=env_sleep
    )
    assert res_sleep.returncode == 0
    time.sleep(0.6)

    res_wait_to = run_ajan(
        ["wait", "en_sleep_task", "--timeout", "0.2"], env=env_sleep
    )
    assert res_wait_to.returncode == 1

    res_cancel = run_ajan(["cancel", "en_sleep_task"], env=env_sleep)
    assert res_cancel.returncode == 0
    meta_sleep = json.loads(
        (state_dir / "en_sleep_task" / "meta.json").read_text(encoding="utf-8")
    )
    assert meta_sleep["durum"] == "iptal"

    # 11. clean --days
    old_dir = state_dir / "en_old_task"
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / "meta.json").write_text(
        json.dumps({"etiket": "en_old_task", "durum": "bitti"}), encoding="utf-8"
    )
    old_ts = time.time() - (10 * 86400)
    os.utime(old_dir, (old_ts, old_ts))

    res_clean = run_ajan(["clean", "--days", "7"], env=env)
    assert res_clean.returncode == 0
    assert not old_dir.exists()


def test_skill_md_frontmatter_tr_ve_en_tetikleyiciler() -> None:
    """
    skills/ajan/SKILL.md frontmatter description alanı mevcut Türkçe tetikleyicileri
    ve istenen İngilizce tetikleyicileri tek satır geçerli YAML string olarak içermelidir.
    """
    skill_path = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "plugins", "gemini-baton", "skills", "ajan", "SKILL.md")
    )
    content = open(skill_path, "r", encoding="utf-8").read()
    lines = content.splitlines()
    assert lines[0].strip() == "---"
    end_idx = lines.index("---", 1)
    fm_lines = lines[1:end_idx]

    desc_lines = [ln for ln in fm_lines if ln.startswith("description:")]
    assert len(desc_lines) == 1
    desc_line = desc_lines[0]
    raw_val = desc_line[len("description:") :].strip()

    # Tek satır YAML string (çok satırlı | veya > blok olmamalı)
    assert raw_val not in ("|", ">", "|-", ">-")
    assert raw_val
    # Tırnak içine alınmamış YAML değerinde ": " bulunmamalı
    if not (
        (raw_val.startswith('"') and raw_val.endswith('"'))
        or (raw_val.startswith("'") and raw_val.endswith("'"))
    ):
        assert ": " not in raw_val

    for trigger in [
        "geminiye ver",
        "hydrogen'e ver",
        "flash'a ver",
        "alt ajana ver",
        "delege et",
        "delegate to Gemini",
        "give this to Gemini",
        "hand off to a sub-agent",
        "use hydrogen",
        "use Gemini for implementation",
    ]:
        assert trigger in desc_line


# ---------------------------------------------------------------------------
# v0.7.0 Sağlamlaştırma Testleri
# ---------------------------------------------------------------------------
def test_run_dogrulama_komut_zaman_asimi_kismi_cikti_ve_dil(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    run_dogrulama_komut zaman aşımında bytes/str kısmi çıktıyı korumalı,
    AJAN_DIL'e göre zaman aşımı notu eklemeli ve çıkış kodu 124 dönmelidir.
    """
    slow_cmd = (
        f'{sys.executable} -c '
        '"import time; print(\'kismi\', flush=True); time.sleep(30)"'
    )

    monkeypatch.setenv("AJAN_DIL", "tr")
    rc_tr, out_tr = ajan.run_dogrulama_komut(slow_cmd, zaman_asimi=1)
    assert rc_tr == 124
    assert "kismi" in out_tr
    assert "Zaman aşımı" in out_tr

    monkeypatch.setenv("AJAN_DIL", "en")
    rc_en, out_en = ajan.run_dogrulama_komut(slow_cmd, zaman_asimi=1)
    assert rc_en == 124
    assert "kismi" in out_en
    assert "Timeout" in out_en

    # bytes stdout (bozuk UTF-8 dahil) + bytes stderr durumu
    def fake_run_timeout(*args: Any, **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(
            cmd="slow",
            timeout=2,
            output=b"kismi_bytes_\xff\n",
            stderr=b"err_bytes\n",
        )

    monkeypatch.setattr(subprocess, "run", fake_run_timeout)
    monkeypatch.setenv("AJAN_DIL", "tr")
    rc_b, out_b = ajan.run_dogrulama_komut("slow", zaman_asimi=2)
    assert rc_b == 124
    assert "kismi_bytes_" in out_b
    assert "err_bytes" in out_b
    assert "Zaman aşımı (2s)" in out_b


def test_cmd_dogrula_zaman_asimi_takip_mesaji_ve_stderr_kuyrugu(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any, capsys: Any
) -> None:
    """
    cmd_dogrula zaman aşımında kısmi çıktıyı takip mesajına (son 40 satır) aktarmalı
    ve DOGRULANAMADI öncesinde son ~20 satırı stderr'e yazdırmalıdır.
    """
    state_dir = tmp_path / "state"
    monkeypatch.setenv("AJAN_DIZIN", str(state_dir))
    task_dir = state_dir / "timeout_dogrula"
    task_dir.mkdir(parents=True, exist_ok=True)
    ajan.save_meta(
        str(task_dir),
        {
            "etiket": "timeout_dogrula",
            "durum": "bitti",
            "conversation_id": "conv-timeout-1",
            "tur": 1,
            "dogrulama": [],
        },
    )

    sent_messages: list[str] = []

    def fake_calistir_devam(
        etiket: str, mesaj: str, bekle: bool = False, zaman_asimi: float | None = None
    ) -> int:
        sent_messages.append(mesaj)
        return 0

    monkeypatch.setattr(ajan, "calistir_devam", fake_calistir_devam)

    slow_cmd = (
        f'{sys.executable} -c '
        '"import time; print(\'kismi_takip\', flush=True); time.sleep(30)"'
    )
    args = type(
        "Args",
        (),
        {
            "etiket": "timeout_dogrula",
            "test": slow_cmd,
            "tur": 1,
            "cwd": None,
            "zaman_asimi": 1,
        },
    )()

    with pytest.raises(SystemExit) as exc:
        ajan.cmd_dogrula(args)
    assert exc.value.code == 1

    captured = capsys.readouterr()
    assert "DOGRULANAMADI (1 tur)" in captured.out
    assert "kismi_takip" in captured.err
    assert "Zaman aşımı" in captured.err

    assert len(sent_messages) == 1
    assert "kismi_takip" in sent_messages[0]
    assert "Zaman aşımı" in sent_messages[0]
    assert "testleri gevşetme" in sent_messages[0]

    # 60 satırlık başarısız çıktıda takip mesajı son 40 satırı, stderr son 20 satırı içermeli
    sent_messages.clear()
    many_lines = "\n".join(f"satir_{i:02d}" for i in range(1, 61))
    monkeypatch.setattr(
        ajan, "run_dogrulama_komut", lambda *a, **kw: (1, many_lines)
    )
    with pytest.raises(SystemExit) as exc2:
        ajan.cmd_dogrula(args)
    assert exc2.value.code == 1

    cap2 = capsys.readouterr()
    assert "DOGRULANAMADI (1 tur)" in cap2.out
    assert "satir_60" in cap2.err
    assert "satir_41" in cap2.err
    assert "satir_40" not in cap2.err

    assert len(sent_messages) == 1
    assert "satir_60" in sent_messages[0]
    assert "satir_21" in sent_messages[0]
    assert "satir_20" not in sent_messages[0]


def test_add_permissions_atomik_yazma_ve_hata_temizligi(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """
    add_permissions settings.json'u atomik yazmalı: sonrasında .tmp kalmamalı,
    os.replace hata verirse orijinal dosya bozulmamalı, tmp temizlenmeli ve ValueError fırlatılmalıdır.
    """
    settings_path = tmp_path / "settings.json"
    orig_content = json.dumps({"permissions": {"allow": ["command(ls)"]}}, indent=2) + "\n"
    settings_path.write_text(orig_content, encoding="utf-8")

    # 1. Başarılı atomik yazma: .tmp kalmamalı, .bak oluşmalı
    bak = add_permissions(["write_file(/tmp/atomik)"], str(settings_path))
    assert bak and os.path.isfile(bak)
    assert list(tmp_path.glob("*.tmp")) == []
    updated = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "write_file(/tmp/atomik)" in updated["permissions"]["allow"]

    # 2. os.replace hata verirse orijinal korunmalı, .tmp temizlenmeli, ValueError fırlatılmalı
    before_fail = settings_path.read_text(encoding="utf-8")

    def failing_replace(src: str, dst: str) -> None:
        assert src.endswith(".tmp")
        assert os.path.exists(src)
        raise OSError("simulated disk full")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(ValueError) as exc_info:
        add_permissions(["command(pytest)"], str(settings_path))
    assert "yazılamadı" in str(exc_info.value)
    assert settings_path.read_text(encoding="utf-8") == before_fail
    assert list(tmp_path.glob("*.tmp")) == []


def test_argparse_help_tr_ve_en(test_env: dict[str, Any]) -> None:
    """
    AJAN_DIL=en iken --help ve alt komut --help çıktıları İngilizce,
    AJAN_DIL yok veya tr iken Türkçe olmalıdır.
    """
    env_en = dict(test_env["env"], AJAN_DIL="en")
    env_default = dict(test_env["env"])
    env_default.pop("AJAN_DIL", None)

    # 1. Ana --help (EN vs varsayılan TR)
    res_en = run_ajan(["--help"], env=env_en)
    assert res_en.returncode == 0
    assert "Start a new" in res_en.stdout
    assert "Yeni bir ajan görevi başlat" not in res_en.stdout

    res_tr = run_ajan(["--help"], env=env_default)
    assert res_tr.returncode == 0
    assert "Yeni bir ajan görevi başlat" in res_tr.stdout
    assert "Start a new" not in res_tr.stdout

    # 2. baslat --help (EN vs varsayılan TR)
    res_baslat_en = run_ajan(["baslat", "--help"], env=env_en)
    assert res_baslat_en.returncode == 0
    assert "Start a new agent task" in res_baslat_en.stdout
    assert "Files containing the task description" in res_baslat_en.stdout
    assert "Görev metnini içeren dosyalar" not in res_baslat_en.stdout

    res_baslat_tr = run_ajan(["baslat", "--help"], env=env_default)
    assert res_baslat_tr.returncode == 0
    assert "Görev metnini içeren dosyalar" in res_baslat_tr.stdout
    assert "Files containing the task description" not in res_baslat_tr.stdout

    # 3. dogrula --help (EN)
    res_dogrula_en = run_ajan(["dogrula", "--help"], env=env_en)
    assert res_dogrula_en.returncode == 0
    assert "Verification command to run" in res_dogrula_en.stdout
    assert "N+1" in res_dogrula_en.stdout
    assert "Çalıştırılacak doğrulama komutu" not in res_dogrula_en.stdout


def test_build_gemini_md_kisa_ve_kritik_kurallar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    build_gemini_md hem TR hem EN için kısa olmalı ve kritik ifadeleri
    (dizin listesi, komutlar, JSON şema anahtarları, testleri gevşetme yasağı) içermelidir.
    """
    required_json_keys = [
        "ozet",
        "degisen_dosyalar",
        "calistirilan_testler",
        "acik_konular",
        "basarili",
    ]
    gorev = "MODUL_GOREVI"

    monkeypatch.setenv("AJAN_DIL", "tr")
    md_tr = ajan.build_gemini_md(["/proje/src", "/proje/tests"], ["pytest -q"], gorev)
    assert "/proje/src" in md_tr and "/proje/tests" in md_tr
    assert "pytest -q" in md_tr
    assert "testleri gevşetme" in md_tr
    assert gorev in md_tr
    for k in required_json_keys:
        assert f'"{k}"' in md_tr
    assert len(md_tr) - len(gorev) < 400

    monkeypatch.setenv("AJAN_DIL", "en")
    md_en = ajan.build_gemini_md(["/proje/src"], ["pytest -q"], gorev)
    assert "/proje/src" in md_en
    assert "pytest -q" in md_en
    assert "do not relax tests" in md_en
    assert gorev in md_en
    for k in required_json_keys:
        assert f'"{k}"' in md_en
    assert len(md_en) - len(gorev) < 400

    # Boş izin listeleri
    assert "none" in ajan.build_gemini_md([], [], "x")
    monkeypatch.setenv("AJAN_DIL", "tr")
    assert "yok" in ajan.build_gemini_md([], [], "x")


def test_hata_agy_bulunamadi_baslat_ve_devam(
    test_env: dict[str, Any], tmp_path: Any
) -> None:
    """
    agy bulunamadığında veya çalıştırılamaz olduğunda baslat ve devam,
    meta/dizin oluşturmadan tek satır hata basıp çıkış kodu 1 vermelidir.
    """
    state_dir = test_env["state_dir"]

    # 1. baslat: var olmayan AJAN_AGY (TR ve EN)
    env_missing = dict(test_env["env"], AJAN_AGY="/nonexistent/agy_missing_bin")
    res_tr = run_ajan(["baslat", "agy_yok_tr", "-m", "test"], env=env_missing)
    assert res_tr.returncode == 1
    assert "Traceback" not in res_tr.stderr
    assert len(res_tr.stderr.strip().splitlines()) == 1
    assert "agy bulunamadı" in res_tr.stderr
    assert not (state_dir / "agy_yok_tr").exists()

    env_missing_en = dict(env_missing, AJAN_DIL="en")
    res_en = run_ajan(["baslat", "agy_yok_en", "-m", "test"], env=env_missing_en)
    assert res_en.returncode == 1
    assert "Traceback" not in res_en.stderr
    assert len(res_en.stderr.strip().splitlines()) == 1
    assert "agy not found" in res_en.stderr
    assert not (state_dir / "agy_yok_en").exists()

    # 2. baslat: çalıştırılabilir olmayan dosya
    non_exec = tmp_path / "not_exec_agy"
    non_exec.write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    non_exec.chmod(0o644)
    env_non_exec = dict(test_env["env"], AJAN_AGY=str(non_exec))
    res_ne = run_ajan(["baslat", "agy_nonexec", "-m", "test"], env=env_non_exec)
    assert res_ne.returncode == 1
    assert "Traceback" not in res_ne.stderr
    assert not (state_dir / "agy_nonexec").exists()

    # 3. devam: mevcut bitmiş görevde agy eksikse meta değişmemeli ve çıkış 1 olmalı
    res_ok = run_ajan(
        ["baslat", "devam_agy_yok", "-m", "ilk tur", "--bekle"], env=test_env["env"]
    )
    assert res_ok.returncode == 0
    meta_before = json.loads(
        (state_dir / "devam_agy_yok" / "meta.json").read_text(encoding="utf-8")
    )

    res_devam = run_ajan(
        ["devam", "devam_agy_yok", "-m", "ikinci tur"], env=env_missing
    )
    assert res_devam.returncode == 1
    assert "Traceback" not in res_devam.stderr
    assert len(res_devam.stderr.strip().splitlines()) == 1
    assert "agy bulunamadı" in res_devam.stderr
    meta_after = json.loads(
        (state_dir / "devam_agy_yok" / "meta.json").read_text(encoding="utf-8")
    )
    assert meta_after["tur"] == meta_before["tur"]
    assert meta_after["durum"] == "bitti"


def test_hata_gecersiz_gorev_dosyasi_dizin_okunamaz_ve_utf8(
    test_env: dict[str, Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    """
    Görev dosyası dizin, bozuk UTF-8 veya okunamayan (OSError) dosya ise
    traceback olmadan tek satır hata basıp çıkış kodu 1 vermelidir.
    """
    env = test_env["env"]
    env_en = dict(env, AJAN_DIL="en")

    # 1. Dizin verilmesi
    a_dir = tmp_path / "gorev_dizini"
    a_dir.mkdir()
    res_dir_tr = run_ajan(["baslat", "dizin_gorev", "-g", str(a_dir)], env=env)
    assert res_dir_tr.returncode == 1
    assert "Traceback" not in res_dir_tr.stderr
    assert len(res_dir_tr.stderr.strip().splitlines()) == 1
    assert "okunamadı" in res_dir_tr.stderr

    res_dir_en = run_ajan(["baslat", "dizin_gorev_en", "-g", str(a_dir)], env=env_en)
    assert res_dir_en.returncode == 1
    assert "Traceback" not in res_dir_en.stderr
    assert len(res_dir_en.stderr.strip().splitlines()) == 1
    assert "Could not read task file" in res_dir_en.stderr

    # 2. Geçersiz UTF-8 dosyası
    bad_utf8 = tmp_path / "bozuk_utf8.bin"
    bad_utf8.write_bytes(b"\x80\xff\xfe\x00gecersiz")
    res_utf8_tr = run_ajan(["baslat", "utf8_gorev", "-g", str(bad_utf8)], env=env)
    assert res_utf8_tr.returncode == 1
    assert "Traceback" not in res_utf8_tr.stderr
    assert len(res_utf8_tr.stderr.strip().splitlines()) == 1
    assert "okunamadı" in res_utf8_tr.stderr

    res_utf8_en = run_ajan(["baslat", "utf8_gorev_en", "-g", str(bad_utf8)], env=env_en)
    assert res_utf8_en.returncode == 1
    assert "Traceback" not in res_utf8_en.stderr
    assert len(res_utf8_en.stderr.strip().splitlines()) == 1
    assert "Could not read task file" in res_utf8_en.stderr

    # 3. OSError (okunamayan dosya)
    unreadable = tmp_path / "okunamaz.md"
    unreadable.write_text("gizli", encoding="utf-8")
    monkeypatch.setenv("AJAN_DIZIN", str(test_env["state_dir"]))
    monkeypatch.setenv("AJAN_AYAR", str(test_env["settings_path"]))
    monkeypatch.setenv("AJAN_AGY", env["AJAN_AGY"])

    orig_open = open

    def fail_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if os.path.abspath(str(file)) == str(unreadable.resolve()):
            raise PermissionError("Permission denied")
        return orig_open(file, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fail_open)
    args = type(
        "Args",
        (),
        {
            "etiket": "okunamaz_gorev",
            "gorev_dosyalari": [str(unreadable)],
            "mesaj": None,
            "model": "neon",
            "effort": None,
            "yaz": [],
            "oku": [],
            "komut": [],
            "sure": None,
            "sandbox": False,
            "izin_ekle": False,
            "bekle": False,
        },
    )()
    with pytest.raises(SystemExit) as exc:
        ajan.cmd_baslat(args)
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Traceback" not in err
    assert len(err.strip().splitlines()) == 1
    assert "okunamadı" in err


def test_hata_settings_yok_ve_yazilamaz(
    test_env: dict[str, Any], tmp_path: Any
) -> None:
    """
    settings.json yokken izin kontrol boş liste gibi davranmalı (çıkış 2);
    settings dizini oluşturulamıyorsa / yazılamıyorsa --izin-ekle traceback olmadan
    tek satır hata basıp çıkış kodu 1 vermelidir.
    """
    # 1. settings.json yok -> çıkış 2 (eksik izin)
    missing_settings = tmp_path / "olmayan_dizin" / "settings.json"
    env_missing = dict(test_env["env"], AJAN_AYAR=str(missing_settings))
    res_check = run_ajan(
        ["izin", "kontrol", "--yaz", "/tmp/x"], env=env_missing
    )
    assert res_check.returncode == 2
    assert "Traceback" not in res_check.stderr

    # 2. settings dizini oluşturulamıyor (üst yol normal dosya)
    blocker = tmp_path / "dosya_engel"
    blocker.write_text("engel", encoding="utf-8")
    blocked_settings = blocker / "alt" / "settings.json"
    env_blocked = dict(test_env["env"], AJAN_AYAR=str(blocked_settings))

    res_izin = run_ajan(
        ["izin", "kontrol", "--yaz", "/tmp/x", "--izin-ekle"], env=env_blocked
    )
    assert res_izin.returncode == 1
    assert "Traceback" not in res_izin.stderr
    assert len(res_izin.stderr.strip().splitlines()) == 1
    assert "yazılamadı" in res_izin.stderr

    res_baslat = run_ajan(
        ["baslat", "yazilamaz_ayar", "-m", "test", "--yaz", "/tmp/x", "--izin-ekle"],
        env=env_blocked,
    )
    assert res_baslat.returncode == 1
    assert "Traceback" not in res_baslat.stderr
    assert len(res_baslat.stderr.strip().splitlines()) == 1
    assert "yazılamadı" in res_baslat.stderr

    # İngilizce hata mesajı
    env_blocked_en = dict(env_blocked, AJAN_DIL="en")
    res_en = run_ajan(
        ["izin", "kontrol", "--yaz", "/tmp/x", "--izin-ekle"], env=env_blocked_en
    )
    assert res_en.returncode == 1
    assert "Traceback" not in res_en.stderr
    assert len(res_en.stderr.strip().splitlines()) == 1
    assert "Could not write" in res_en.stderr


# ---------------------------------------------------------------------------
# Dinamik Model Kataloğu Testleri
# ---------------------------------------------------------------------------
def test_parse_models_output() -> None:
    """parse_models_output ilk satırı/sekmesiz satırları atlamalı, tekrarları elemeli ve sırayı korumalıdır."""
    raw = (
        "Fetching available models...\n"
        "WARN: some notice without tab\n"
        "Error:\tnot a model id\n"
        "12345\tnumeric only\n"
        "gemini-4-neon-high\tGemini 4 Neon (High)\n"
        "gemini-4-neon-xhigh\tGemini 4 Neon (XHigh)\n"
        "gemini-4-neon-high\tGemini 4 Neon (High Duplicate)\n"
        "\x1b[32mgemini-3.8-flash-high\x1b[0m\tGemini 3.8 Flash (High)\n"
        "claude-opus-5-5-high\tClaude Opus 5.5 (High)\n"
        "gpt-oss-120b-medium\tGPT-OSS 120B (Medium)\n"
        "bad id with space\tShould Skip\n"
        "empty-name-model\t   \n"
    )
    parsed = ajan.parse_models_output(raw)
    assert [m["id"] for m in parsed] == [
        "gemini-4-neon-high",
        "gemini-4-neon-xhigh",
        "gemini-3.8-flash-high",
        "claude-opus-5-5-high",
        "gpt-oss-120b-medium",
    ]
    assert parsed[0] == {"id": "gemini-4-neon-high", "ad": "Gemini 4 Neon (High)"}
    assert ajan.parse_models_output("") == []
    assert ajan.parse_models_output("Fetching available models...\nno tabs\n") == []


def test_build_aliases_ve_surum_siralamasi() -> None:
    """
    build_aliases aile/seviye takma adlarını üretmeli, orchestrator/Gemini dışı modelleri atlamalı,
    aynı ailede sayısal sürüm karşılaştırmasıyla (4 > 3.8, 3.10 > 3.9) en yüksek sürümü seçmelidir.
    """
    models = [
        {"id": "gemini-3.8-neon-low", "ad": "Old Neon Low"},
        {"id": "gemini-3.8-neon-xhigh", "ad": "Old Neon XHigh"},
        {"id": "gemini-4-neon-high", "ad": "Gemini 4 Neon (High)"},
        {"id": "gemini-4-neon-xhigh", "ad": "Gemini 4 Neon (XHigh)"},
        {"id": "gemini-4-neon-medium", "ad": "Gemini 4 Neon (Medium)"},
        {"id": "gemini-4-neon-low", "ad": "Gemini 4 Neon (Low)"},
        {"id": "gemini-3.8-flash-high", "ad": "Gemini 3.8 Flash (High)"},
        {"id": "gemini-3.8-flash-medium", "ad": "Gemini 3.8 Flash (Medium)"},
        {"id": "gemini-3.8-flash-low", "ad": "Gemini 3.8 Flash (Low)"},
        {"id": "gemini-3.9-krypton-xhigh", "ad": "Krypton 3.9 XHigh"},
        {"id": "gemini-3.9-krypton-low", "ad": "Krypton 3.9 Low"},
        {"id": "gemini-3.10-krypton-high", "ad": "Krypton 3.10 High"},
        {"id": "gemini-3.10-krypton-medium", "ad": "Krypton 3.10 Medium"},
        {"id": "gemini-pro-orchestrator-neon", "ad": "Orchestrator (Neon)"},
        {"id": "claude-opus-5-5-high", "ad": "Claude Opus 5.5 (High)"},
    ]
    fams = ajan.families(models)
    assert fams["neon"]["surum"] == (4,)
    assert fams["krypton"]["surum"] == (3, 10)
    # 3.10 sürümü kazanınca 3.9'un xhigh/low seviyeleri karışmamalı
    assert set(fams["krypton"]["seviyeler"].keys()) == {"high", "medium"}
    assert "orchestrator" not in fams

    aliases = ajan.build_aliases(models)
    assert aliases["neon"] == "gemini-4-neon-xhigh"
    assert aliases["neon-high"] == "gemini-4-neon-high"
    assert aliases["neon-orta"] == "gemini-4-neon-medium"
    assert aliases["neon-low"] == "gemini-4-neon-low"
    assert aliases["flash"] == "gemini-3.8-flash-high"
    assert aliases["flash-orta"] == "gemini-3.8-flash-medium"
    assert aliases["flash-low"] == "gemini-3.8-flash-low"
    assert aliases["krypton"] == "gemini-3.10-krypton-high"
    assert aliases["krypton-high"] == "gemini-3.10-krypton-high"
    assert aliases["krypton-orta"] == "gemini-3.10-krypton-medium"
    assert "krypton-low" not in aliases
    # orchestrator ve Gemini dışı modeller takma ad üretmez
    assert all("orchestrator" not in k for k in aliases)
    assert all("claude" not in k for k in aliases)


def test_legacy_uyum_ve_dinamik_takma_adlar(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """
    Eski sabit takma adlar (ör. argon -> gemini-4-argon-high) katalogda o seviye olmasa bile
    korunmalı; yeni dinamik adlar (neon-low, krypton, argon-high, flash-low) çözülmelidir.
    """
    models_file = tmp_path / "models_dynamic.txt"
    models_file.write_text(
        "Fetching available models...\n"
        "gemini-4-neon-xhigh\tGemini 4 Neon (XHigh)\n"
        "gemini-4-neon-low\tGemini 4 Neon (Low)\n"
        "gemini-4-argon-medium\tGemini 4 Argon (Medium)\n"
        "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
        "gemini-3.8-flash-low\tGemini 3.8 Flash (Low)\n"
        "gemini-5-krypton-xhigh\tGemini 5 Krypton (XHigh)\n"
        "gemini-5-krypton-medium\tGemini 5 Krypton (Medium)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_AGY_MODELS", str(models_file))
    ajan._CATALOG_MEMO.clear()

    # Katalogda yalnızca argon-medium olsa bile LEGACY önceliği korunur
    assert resolve_model("argon") == "gemini-4-argon-high"
    assert resolve_model("argon-orta") == "gemini-4-argon-medium"
    assert resolve_model("flash-orta") == "gemini-3.8-flash-medium"
    # Yeni dinamik takma adlar
    assert resolve_model("neon-low") == "gemini-4-neon-low"
    assert resolve_model("flash-low") == "gemini-3.8-flash-low"
    assert resolve_model("krypton") == "gemini-5-krypton-xhigh"
    assert resolve_model("krypton-orta") == "gemini-5-krypton-medium"
    # Katalogda argon-high eklenirse dinamik olarak çözümlenir
    models_file.write_text(
        models_file.read_text(encoding="utf-8")
        + "gemini-4-argon-high\tGemini 4 Argon (High)\n",
        encoding="utf-8",
    )
    ajan.load_catalog(refresh=True)
    assert resolve_model("argon-high") == "gemini-4-argon-high"


def test_default_model_tercih_sirasi_ve_yedekler() -> None:
    """
    default_model tercih sırasını (neon -> hydrogen -> argon -> flash) izlemeli,
    yeni aileyi varsayılan yapmamalı ve hiç Gemini yoksa DEFAULT_MODEL dönmelidir.
    """
    # 1. neon yoksa hydrogen
    only_hydrogen_up = [
        {"id": "gemini-4-hydrogen-xhigh", "ad": "Hydrogen XHigh"},
        {"id": "gemini-4-argon-medium", "ad": "Argon Medium"},
        {"id": "gemini-3.8-flash-high", "ad": "Flash High"},
    ]
    assert ajan.default_model(only_hydrogen_up) == "gemini-4-hydrogen-xhigh"

    # 2. neon ve hydrogen yoksa argon (katalogda yalnız argon-medium varsa onu seçer)
    only_argon_medium = [
        {"id": "gemini-4-argon-medium", "ad": "Argon Medium"},
        {"id": "gemini-3.8-flash-high", "ad": "Flash High"},
    ]
    assert ajan.default_model(only_argon_medium) == "gemini-4-argon-medium"

    # argon-high katalogda varsa eski davranışla uyumlu argon-high seçer
    argon_with_high = [
        {"id": "gemini-4-argon-high", "ad": "Argon High"},
        {"id": "gemini-4-argon-medium", "ad": "Argon Medium"},
    ]
    assert ajan.default_model(argon_with_high) == "gemini-4-argon-high"

    # 3. hiç Gemini yoksa DEFAULT_MODEL
    non_gemini_only = [
        {"id": "claude-opus-5-5-high", "ad": "Claude Opus 5.5"},
        {"id": "gpt-oss-120b-medium", "ad": "GPT-OSS 120B"},
    ]
    assert ajan.default_model(non_gemini_only) == DEFAULT_MODEL

    # 4. yalnız yeni (tercih dışı) aile varsa varsayılan yapılmaz -> DEFAULT_MODEL
    unknown_family_only = [
        {"id": "gemini-5-krypton-xhigh", "ad": "Krypton XHigh"},
    ]
    assert ajan.default_model(unknown_family_only) == DEFAULT_MODEL


def test_ajan_model_onceligi_ve_cli_model_ezer(
    test_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    AJAN_MODEL ortam değişkeni takma ad veya tam kimlik olarak varsayılanı belirlemeli;
    --model verildiğinde AJAN_MODEL yok sayılmalıdır.
    """
    # Birim düzeyinde AJAN_MODEL: takma ad, tam kimlik ve boş değer
    monkeypatch.setenv("AJAN_MODEL", "hydrogen")
    assert ajan.default_model() == "gemini-4-hydrogen-xhigh"
    assert resolve_model(None) == "gemini-4-hydrogen-xhigh"
    assert resolve_model("") == "gemini-4-hydrogen-xhigh"

    monkeypatch.setenv("AJAN_MODEL", "claude-opus-5-5-high")
    assert ajan.default_model() == "claude-opus-5-5-high"

    monkeypatch.setenv("AJAN_MODEL", "   ")
    assert ajan.default_model() == "gemini-4-neon-xhigh"
    monkeypatch.delenv("AJAN_MODEL", raising=False)

    # CLI düzeyinde: AJAN_MODEL=hydrogen iken --model olmadan başlatma
    env = dict(test_env["env"], AJAN_MODEL="hydrogen")
    log_path = test_env["log_path"]

    res1 = run_ajan(["baslat", "env_model_g", "-m", "test1", "--bekle"], env=env)
    assert res1.returncode == 0, res1.stderr

    # CLI düzeyinde: --model flash-orta verildiğinde AJAN_MODEL ezilir
    res2 = run_ajan(
        [
            "baslat",
            "cli_model_g",
            "-m",
            "test2",
            "--model",
            "flash-orta",
            "--bekle",
        ],
        env=env,
    )
    assert res2.returncode == 0, res2.stderr

    calls = [
        json.loads(line)
        for line in open(log_path, encoding="utf-8")
        if line.strip()
    ]
    assert len(calls) == 2

    argv1 = calls[0]["argv"]
    assert argv1[argv1.index("--model") + 1] == "gemini-4-hydrogen-xhigh"

    argv2 = calls[1]["argv"]
    assert argv2[argv2.index("--model") + 1] == "gemini-3.8-flash-medium"

    # meta.model verilmediğinde durum '-' göstermeli
    res_durum = run_ajan(["durum", "env_model_g", "--json"], env=env)
    assert res_durum.returncode == 0
    assert json.loads(res_durum.stdout)["model"] == "-"


def test_katalog_onbellek_ttl_ve_cagri_sayisi(test_env: dict[str, Any]) -> None:
    """
    Taze önbellek varken agy models tekrar çağrılmamalı;
    fetched_at TTL'den eski olduğunda yeniden agy models çağrılmalıdır.
    """
    env = dict(test_env["env"])
    state_dir = test_env["state_dir"]
    models_log = test_env["models_log_path"]

    def count_model_calls() -> int:
        if not os.path.isfile(models_log):
            return 0
        with open(models_log, "r", encoding="utf-8") as f:
            return len([ln for ln in f if ln.strip()])

    # 1. İlk çağrı agy models'i 1 kez çalıştırır ve önbelleği yazar
    res1 = run_ajan(["baslat", "ttl_gorev", "-m", "1. tur", "--bekle"], env=env)
    assert res1.returncode == 0, res1.stderr
    assert count_model_calls() == 1
    cache_file = state_dir / "models_cache.json"
    assert cache_file.is_file()

    # 2. Taze önbellek varken devam ve modeller komutları agy models çağırmaz
    res2 = run_ajan(["devam", "ttl_gorev", "-m", "2. tur", "--bekle"], env=env)
    assert res2.returncode == 0, res2.stderr
    res3 = run_ajan(["modeller", "--json"], env=env)
    assert res3.returncode == 0
    assert json.loads(res3.stdout)["kaynak"] == "onbellek"
    assert count_model_calls() == 1

    # 3. Önbelleği bayatlat (25 saat geriye çek) -> tekrar agy çağrılır
    cache_data = json.loads(cache_file.read_text(encoding="utf-8"))
    cache_data["fetched_at"] = time.time() - (25 * 3600)
    cache_file.write_text(json.dumps(cache_data), encoding="utf-8")

    res4 = run_ajan(["modeller", "--json"], env=env)
    assert res4.returncode == 0
    assert json.loads(res4.stdout)["kaynak"] == "agy"
    assert count_model_calls() == 2


def test_katalog_agy_hatasi_zaman_asimi_ve_bozuk_onbellek(
    test_env: dict[str, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """
    agy hata/zaman aşımında varsa bayat önbelleğe, yoksa BUILTIN_MODELS'e düşmeli;
    bozuk önbellek JSON'u yok sayılmalı ve agy models hatasında görev yine başlamalıdır.
    """
    state_dir = test_env["state_dir"]
    cache_file = state_dir / "models_cache.json"

    # 1. Önbellek yokken agy models başarısız -> yerleşik liste + görev yine başlar
    env_fail = dict(test_env["env"], FAKE_AGY_MODELS_FAIL="1")
    res_m = run_ajan(["modeller", "--json"], env=env_fail)
    assert res_m.returncode == 0
    data_builtin = json.loads(res_m.stdout)
    assert data_builtin["kaynak"] == "yerlesik"
    assert data_builtin["varsayilan"] == DEFAULT_MODEL
    assert not cache_file.exists()

    res_task = run_ajan(
        ["baslat", "fail_models_gorev", "-m", "yerleşik ile başla", "--bekle"],
        env=env_fail,
    )
    assert res_task.returncode == 0, res_task.stderr

    # 2. Bayat önbellek varken agy başarısız -> bayat önbelleğe düşer ve dosyaya dokunmaz
    stale_ts = time.time() - (48 * 3600)
    stale_payload = {
        "fetched_at": stale_ts,
        "models": [
            {"id": "gemini-4-hydrogen-xhigh", "ad": "Stale Hydrogen XHigh"},
        ],
    }
    cache_file.write_text(json.dumps(stale_payload), encoding="utf-8")
    res_stale = run_ajan(["modeller", "--json"], env=env_fail)
    assert res_stale.returncode == 0
    data_stale = json.loads(res_stale.stdout)
    assert data_stale["kaynak"] == "onbellek"
    assert data_stale["varsayilan"] == "gemini-4-hydrogen-xhigh"
    assert json.loads(cache_file.read_text(encoding="utf-8"))["fetched_at"] == stale_ts

    # 3. Bozuk önbellek JSON'u -> önbellek yok sayılır
    cache_file.write_text("{bozuk json!!!", encoding="utf-8")
    res_corrupt_fail = run_ajan(["modeller", "--json"], env=env_fail)
    assert res_corrupt_fail.returncode == 0
    assert json.loads(res_corrupt_fail.stdout)["kaynak"] == "yerlesik"

    # agy çalışınca bozuk önbelleğin üzerine geçerli önbellek yazar
    res_corrupt_ok = run_ajan(["modeller", "--json"], env=test_env["env"])
    assert res_corrupt_ok.returncode == 0
    assert json.loads(res_corrupt_ok.stdout)["kaynak"] == "agy"
    assert isinstance(json.loads(cache_file.read_text(encoding="utf-8")), dict)

    # 4. subprocess.TimeoutExpired exception sızdırmadan yerleşik listeye düşer
    timeout_state = tmp_path / "timeout_state"
    timeout_state.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("AJAN_DIZIN", str(timeout_state))
    ajan._CATALOG_MEMO.clear()

    def fake_run_timeout(*a: Any, **kw: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd=["agy", "models"], timeout=20)

    monkeypatch.setattr(subprocess, "run", fake_run_timeout)
    cat = ajan.load_catalog(refresh=True)
    assert cat["kaynak"] == "yerlesik"
    assert len(cat["models"]) == len(ajan.BUILTIN_MODELS)
    monkeypatch.undo()

    # 5. Önbellek yazılamazsa (OSError) sessizce devam eder ve agy sonucunu döner
    blocker = tmp_path / "dosya_engel_cache"
    blocker.write_text("engel", encoding="utf-8")
    monkeypatch.setenv("AJAN_DIZIN", str(blocker / "alt"))
    monkeypatch.setenv("AJAN_AGY", test_env["env"]["AJAN_AGY"])
    ajan._CATALOG_MEMO.clear()
    cat_unwritable = ajan.load_catalog(refresh=True)
    assert cat_unwritable["kaynak"] == "agy"
    assert len(cat_unwritable["models"]) == 10


def test_yeni_aile_bildirimi(test_env: dict[str, Any], tmp_path: Any) -> None:
    """
    İlk önbellek oluşturmada sessiz olmalı; sonraki yenilemede yeni Gemini ailesi (krypton)
    gelince stderr'e tek satır bildirmeli, varsayılanı değiştirmemeli ve ikinci yenilemede tekrarlamamalıdır.
    """
    base_models = tmp_path / "models_base.txt"
    base_models.write_text(DEFAULT_FAKE_MODELS_OUTPUT, encoding="utf-8")

    env = dict(test_env["env"], FAKE_AGY_MODELS=str(base_models))

    # 1. İlk önbellek oluşumu: stderr sessiz
    res_init = run_ajan(["modeller", "--json"], env=env)
    assert res_init.returncode == 0
    assert res_init.stderr.strip() == ""

    # 2. Katalogda krypton belirir -> yenilemede stderr'de tek satır bildirim
    with_krypton = tmp_path / "models_krypton.txt"
    with_krypton.write_text(
        DEFAULT_FAKE_MODELS_OUTPUT
        + "gemini-5-krypton-xhigh\tGemini 5 Krypton (XHigh)\n"
        + "gemini-5-krypton-medium\tGemini 5 Krypton (Medium)\n",
        encoding="utf-8",
    )
    env_k = dict(test_env["env"], FAKE_AGY_MODELS=str(with_krypton))

    res_new = run_ajan(["modeller", "--yenile", "--json"], env=env_k)
    assert res_new.returncode == 0
    err_lines = [ln for ln in res_new.stderr.splitlines() if ln.strip()]
    assert len(err_lines) == 1
    assert "krypton" in err_lines[0]
    assert "AJAN_MODEL=krypton" in err_lines[0]
    assert "--model krypton" in err_lines[0]

    # Yeni aile varsayılan yapılmamalı
    data_k = json.loads(res_new.stdout)
    assert data_k["varsayilan"] == "gemini-4-neon-xhigh"
    assert data_k["takma_adlar"]["krypton"] == "gemini-5-krypton-xhigh"

    # 3. İkinci yenilemede tekrar bildirilmez
    res_again = run_ajan(["modeller", "--yenile", "--json"], env=env_k)
    assert res_again.returncode == 0
    assert res_again.stderr.strip() == ""

    # 4. Birden çok yeni aile (EN dilinde) virgülle birleştirilmiş tek satır
    with_two = tmp_path / "models_two_new.txt"
    with_two.write_text(
        with_krypton.read_text(encoding="utf-8")
        + "gemini-5-xenon-high\tGemini 5 Xenon (High)\n"
        + "gemini-5-radon-high\tGemini 5 Radon (High)\n",
        encoding="utf-8",
    )
    env_two_en = dict(
        test_env["env"], FAKE_AGY_MODELS=str(with_two), AJAN_DIL="en"
    )
    res_two = run_ajan(["models", "--refresh", "--json"], env=env_two_en)
    assert res_two.returncode == 0
    err_two_lines = [ln for ln in res_two.stderr.splitlines() if ln.strip()]
    assert len(err_two_lines) == 1
    assert "xenon, radon" in err_two_lines[0]
    assert "AJAN_MODEL=xenon" in err_two_lines[0]


def test_modeller_komutu_json_metin_ve_alias(test_env: dict[str, Any]) -> None:
    """
    modeller --json, modeller metin çıktısı ve models --refresh alias'ının
    beklenen alanları ve okunabilir biçimi ürettiğini doğrular.
    """
    env = dict(test_env["env"])

    # 1. modeller --json
    res_json = run_ajan(["modeller", "--json"], env=env)
    assert res_json.returncode == 0, res_json.stderr
    data = json.loads(res_json.stdout)
    assert data["kaynak"] == "agy"
    assert data["varsayilan"] == "gemini-4-neon-xhigh"
    assert data["varsayilan_aile"] == "neon"
    assert data["takma_adlar"]["neon"] == "gemini-4-neon-xhigh"
    assert data["takma_adlar"]["neon-low"] == "gemini-4-neon-low"
    assert data["aileler"]["neon"]["surum"] == "4"
    assert data["aileler"]["flash"]["surum"] == "3.8"
    assert data["aileler"]["neon"]["seviyeler"]["xhigh"] == "gemini-4-neon-xhigh"
    assert isinstance(data["modeller"], list) and len(data["modeller"]) == 10

    # 2. modeller metin çıktısı (önbellekten)
    res_txt = run_ajan(["modeller"], env=env)
    assert res_txt.returncode == 0, res_txt.stderr
    assert "önbellek" in res_txt.stdout
    assert "neon" in res_txt.stdout
    assert "*" in res_txt.stdout
    assert "(varsayılan)" in res_txt.stdout
    assert "gemini-pro-orchestrator-neon" in res_txt.stdout
    assert "Gemini dışı modeller" in res_txt.stdout
    assert "claude-opus-5-5-high" in res_txt.stdout

    # 3. İngilizce alias: models --refresh (AJAN_DIL=en)
    env_en = dict(env, AJAN_DIL="en")
    res_en = run_ajan(["models", "--refresh"], env=env_en)
    assert res_en.returncode == 0, res_en.stderr
    assert "Source: agy" in res_en.stdout
    assert "(default)" in res_en.stdout
    assert "Non-Gemini models" in res_en.stdout


def test_gecersiz_model_ipucu_baton_modeller_icerir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Geçersiz model ipucu hem TR hem EN çıktısında 'baton modeller' içermelidir."""
    monkeypatch.setenv("AJAN_DIL", "tr")
    assert "baton modeller" in ajan.tr("hint_invalid_model")
    monkeypatch.setenv("AJAN_DIL", "en")
    assert "baton modeller" in ajan.tr("hint_invalid_model")


# ---------------------------------------------------------------------------
# v0.8.0 Orkestra Modu Testleri
# ---------------------------------------------------------------------------
def test_orkestra_takma_ad_turetme_ve_cozumleme(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """
    Orkestratör takma adları ayrı fonksiyonda türetilmeli, neon öncelikli olmalı,
    g1-pro için argon istisnası üretilmeli ve build_aliases/Gemini takma adları değişmemelidir.
    """
    # BUILTIN_MODELS hem neon hem g1-pro orkestratörlerini içerir
    builtin_ids = [m["id"] for m in ajan.BUILTIN_MODELS]
    assert "gemini-pro-orchestrator-neon" in builtin_ids
    assert "gemini-pro-orchestrator-g1-pro" in builtin_ids

    # 1. neon + g1-pro (g1-pro önce gelse bile orkestra -> neon, tekrarlar elenir)
    models_both = [
        {"id": "gemini-4-neon-xhigh", "ad": "Gemini 4 Neon (XHigh)"},
        {"id": "gemini-3.8-flash-medium", "ad": "Gemini 3.8 Flash (Medium)"},
        {"id": "gemini-pro-orchestrator-g1-pro", "ad": "Orchestrator (Argon)"},
        {"id": "gemini-pro-orchestrator-neon", "ad": "Orchestrator (Neon)"},
        {"id": "gemini-pro-orchestrator-neon", "ad": "Orchestrator (Neon Dup)"},
        {"id": "claude-opus-5-5-high", "ad": "Claude Opus 5.5 (High)"},
    ]
    orchs = ajan.orchestrators(models_both)
    assert orchs == [
        {
            "id": "gemini-pro-orchestrator-g1-pro",
            "ad": "Orchestrator (Argon)",
            "sonek": "g1-pro",
        },
        {
            "id": "gemini-pro-orchestrator-neon",
            "ad": "Orchestrator (Neon)",
            "sonek": "neon",
        },
    ]

    orch_aliases = ajan.build_orchestrator_aliases(models_both)
    assert orch_aliases == {
        "orkestra": "gemini-pro-orchestrator-neon",
        "orchestrator": "gemini-pro-orchestrator-neon",
        "orkestra-g1-pro": "gemini-pro-orchestrator-g1-pro",
        "orchestrator-g1-pro": "gemini-pro-orchestrator-g1-pro",
        "orkestra-argon": "gemini-pro-orchestrator-g1-pro",
        "orchestrator-argon": "gemini-pro-orchestrator-g1-pro",
        "orkestra-neon": "gemini-pro-orchestrator-neon",
        "orchestrator-neon": "gemini-pro-orchestrator-neon",
    }

    # build_aliases hâlâ orkestra/orchestrator üretmez
    gemini_aliases = ajan.build_aliases(models_both)
    assert all("orchestrator" not in k and "orkestra" not in k for k in gemini_aliases)

    # 2. neon yoksa (yalnız g1-pro) -> orkestra/orchestrator -> g1-pro
    models_only_g1 = [
        {"id": "gemini-4-neon-xhigh", "ad": "Gemini 4 Neon (XHigh)"},
        {"id": "gemini-pro-orchestrator-g1-pro", "ad": "Orchestrator (Argon)"},
    ]
    aliases_g1 = ajan.build_orchestrator_aliases(models_only_g1)
    assert aliases_g1["orkestra"] == "gemini-pro-orchestrator-g1-pro"
    assert aliases_g1["orchestrator"] == "gemini-pro-orchestrator-g1-pro"
    assert aliases_g1["orkestra-g1-pro"] == "gemini-pro-orchestrator-g1-pro"
    assert aliases_g1["orkestra-argon"] == "gemini-pro-orchestrator-g1-pro"
    assert aliases_g1["orchestrator-argon"] == "gemini-pro-orchestrator-g1-pro"

    # neon yok, birden çok orkestratör -> katalogdaki ilk orkestratör seçilir
    models_first_fallback = [
        {"id": "gemini-pro-orchestrator-alpha", "ad": "Orchestrator (Alpha)"},
        {"id": "gemini-pro-orchestrator-g1-pro", "ad": "Orchestrator (Argon)"},
    ]
    aliases_first = ajan.build_orchestrator_aliases(models_first_fallback)
    assert aliases_first["orkestra"] == "gemini-pro-orchestrator-alpha"
    assert aliases_first["orchestrator"] == "gemini-pro-orchestrator-alpha"

    # 3. Katalog üzerinden resolve_model doğrulaması (neon + g1-pro)
    models_file = tmp_path / "models_with_orch.txt"
    models_file.write_text(
        "Fetching available models...\n"
        "gemini-4-neon-xhigh\tGemini 4 Neon (XHigh)\n"
        "gemini-3.8-flash-medium\tGemini 3.8 Flash (Medium)\n"
        "gemini-pro-orchestrator-neon\tOrchestrator (Neon)\n"
        "gemini-pro-orchestrator-g1-pro\tOrchestrator (Argon)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_AGY_MODELS", str(models_file))
    ajan._CATALOG_MEMO.clear()
    ajan.load_catalog(refresh=True)

    assert resolve_model("orkestra") == "gemini-pro-orchestrator-neon"
    assert resolve_model("orchestrator") == "gemini-pro-orchestrator-neon"
    assert resolve_model("orkestra-neon") == "gemini-pro-orchestrator-neon"
    assert resolve_model("orchestrator-neon") == "gemini-pro-orchestrator-neon"
    assert resolve_model("orkestra-g1-pro") == "gemini-pro-orchestrator-g1-pro"
    assert resolve_model("orchestrator-g1-pro") == "gemini-pro-orchestrator-g1-pro"
    assert resolve_model("orkestra-argon") == "gemini-pro-orchestrator-g1-pro"
    assert resolve_model("orchestrator-argon") == "gemini-pro-orchestrator-g1-pro"
    # Mevcut Gemini takma adları değişmez
    assert resolve_model("neon") == "gemini-4-neon-xhigh"
    assert resolve_model("flash-orta") == "gemini-3.8-flash-medium"
    assert resolve_model("argon") == "gemini-4-argon-high"

    # 4. Orkestratör yoksa sözlük boş ve resolve_model("orkestra") çözülmeden kalır
    no_orch_models = [
        {"id": "gemini-4-neon-xhigh", "ad": "Gemini 4 Neon (XHigh)"},
        {"id": "claude-opus-5-5-high", "ad": "Claude Opus 5.5 (High)"},
    ]
    assert ajan.orchestrators(no_orch_models) == []
    assert ajan.build_orchestrator_aliases(no_orch_models) == {}

    no_orch_file = tmp_path / "models_no_orch.txt"
    no_orch_file.write_text(
        "Fetching available models...\n"
        "gemini-4-neon-xhigh\tGemini 4 Neon (XHigh)\n"
        "claude-opus-5-5-high\tClaude Opus 5.5 (High)\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAKE_AGY_MODELS", str(no_orch_file))
    ajan._CATALOG_MEMO.clear()
    ajan.load_catalog(refresh=True)

    assert resolve_model("orkestra") == "orkestra"
    assert resolve_model("orchestrator") == "orchestrator"
    assert resolve_model("neon") == "gemini-4-neon-xhigh"


def test_orkestra_cli_bayraklari_ve_effort_davranisi(
    test_env: dict[str, Any],
) -> None:
    """
    --orkestra ve --orchestrate bayrakları agy'ye orkestratör modelini iletmeli,
    --effort verilmedikçe (baslat ve devam turlarında) argv'ye --effort eklememeli,
    açıkça verildiğinde ise iletmelidir.
    """
    env = dict(test_env["env"])
    state_dir = test_env["state_dir"]
    log_path = test_env["log_path"]

    # 1. baslat --orkestra --sandbox --bekle (effort yok)
    res1 = run_ajan(
        [
            "baslat",
            "ork_gorev",
            "-m",
            "Orkestra görevi",
            "--orkestra",
            "--sandbox",
            "--bekle",
        ],
        env=env,
    )
    assert res1.returncode == 0, res1.stderr

    meta1 = json.loads(
        (state_dir / "ork_gorev" / "meta.json").read_text(encoding="utf-8")
    )
    assert meta1["model"] == "orkestra"
    assert meta1["effort"] is None

    # 2. devam turunda da --effort eklenmemeli ve orkestratör modeli korunmalı
    res2 = run_ajan(
        ["devam", "ork_gorev", "-m", "Takip turu", "--bekle"],
        env=env,
    )
    assert res2.returncode == 0, res2.stderr

    # 3. --orkestra --effort high -> --effort high aktarılmalı
    res3 = run_ajan(
        [
            "baslat",
            "ork_effort_gorev",
            "-m",
            "Effort testi",
            "--orkestra",
            "--effort",
            "high",
            "--sandbox",
            "--bekle",
        ],
        env=env,
    )
    assert res3.returncode == 0, res3.stderr

    # 4. --orchestrate eşdeğeri (effort yok)
    res4 = run_ajan(
        [
            "start",
            "ork_en_gorev",
            "-m",
            "Orchestrate alias",
            "--orchestrate",
            "--sandbox",
            "--wait",
        ],
        env=env,
    )
    assert res4.returncode == 0, res4.stderr

    calls = [
        json.loads(line)
        for line in open(log_path, encoding="utf-8")
        if line.strip()
    ]
    assert len(calls) == 4

    argv1 = calls[0]["argv"]
    assert argv1[argv1.index("--model") + 1] == "gemini-pro-orchestrator-neon"
    assert "--effort" not in argv1
    assert "--sandbox" in argv1

    argv2 = calls[1]["argv"]
    assert argv2[argv2.index("--model") + 1] == "gemini-pro-orchestrator-neon"
    assert "--conversation" in argv2
    assert "--effort" not in argv2

    argv3 = calls[2]["argv"]
    assert argv3[argv3.index("--model") + 1] == "gemini-pro-orchestrator-neon"
    assert argv3[argv3.index("--effort") + 1] == "high"

    argv4 = calls[3]["argv"]
    assert argv4[argv4.index("--model") + 1] == "gemini-pro-orchestrator-neon"
    assert "--effort" not in argv4

    # Yardım çıktılarında --orkestra baslat'ta var (TR/EN), dogrula'da yok
    res_help_tr = run_ajan(["baslat", "--help"], env=env)
    assert res_help_tr.returncode == 0
    assert "--orkestra" in res_help_tr.stdout
    assert "--orchestrate" in res_help_tr.stdout

    res_help_en = run_ajan(
        ["baslat", "--help"], env=dict(env, AJAN_DIL="en")
    )
    assert res_help_en.returncode == 0
    assert "--orkestra" in res_help_en.stdout
    assert "orchestrator model" in res_help_en.stdout.lower()

    res_dogrula_help = run_ajan(["dogrula", "--help"], env=env)
    assert res_dogrula_help.returncode == 0
    assert "--orkestra" not in res_dogrula_help.stdout
    assert "--orchestrate" not in res_dogrula_help.stdout


def test_orkestra_ve_model_birlikte_hata_ve_dizin_olusturmaz(
    test_env: dict[str, Any],
) -> None:
    """
    --orkestra ile --model birlikte verildiğinde görev dizini oluşturulmadan
    TR/EN hata mesajı ile çıkış kodu 1 verilmelidir.
    """
    env = dict(test_env["env"])
    state_dir = test_env["state_dir"]

    # 1. Türkçe hata
    res_tr = run_ajan(
        [
            "baslat",
            "cakisan_tr",
            "-m",
            "test",
            "--orkestra",
            "--model",
            "neon",
        ],
        env=env,
    )
    assert res_tr.returncode == 1
    assert "Traceback" not in res_tr.stderr
    assert len(res_tr.stderr.strip().splitlines()) == 1
    assert ajan.MESSAGES["tr"]["err_orkestra_ve_model"] in res_tr.stderr
    assert not (state_dir / "cakisan_tr").exists()

    # 2. İngilizce hata (--orchestrate + --model)
    env_en = dict(env, AJAN_DIL="en")
    res_en = run_ajan(
        [
            "start",
            "cakisan_en",
            "-m",
            "test",
            "--orchestrate",
            "--model",
            "neon",
        ],
        env=env_en,
    )
    assert res_en.returncode == 1
    assert "Traceback" not in res_en.stderr
    assert len(res_en.stderr.strip().splitlines()) == 1
    assert ajan.MESSAGES["en"]["err_orkestra_ve_model"] in res_en.stderr
    assert not (state_dir / "cakisan_en").exists()


def test_modeller_orkestrator_metin_ve_json(
    test_env: dict[str, Any], tmp_path: Any
) -> None:
    """
    modeller metin çıktısı ayrı 'Orkestratör:' / 'Orchestrators:' bölümü göstermeli,
    orkestratörleri 'Diğer Gemini modelleri'nden çıkarmalı; --json 'orkestra' anahtarını
    eklerken mevcut anahtarları korumalı; orkestratörsüz katalogda bölüm basılmamalıdır.
    """
    rich_models = tmp_path / "models_rich.txt"
    rich_models.write_text(
        "Fetching available models...\n"
        "gemini-4-neon-xhigh\tGemini 4 Neon (XHigh)\n"
        "gemini-3.8-flash-high\tGemini 3.8 Flash (High)\n"
        "gemini-pro-orchestrator-neon\tOrchestrator (Neon)\n"
        "gemini-pro-orchestrator-g1-pro\tOrchestrator (Argon)\n"
        "gemini-2.5-pro-preview\tGemini 2.5 Pro Preview\n"
        "claude-opus-5-5-high\tClaude Opus 5.5 (High)\n",
        encoding="utf-8",
    )
    env = dict(test_env["env"], FAKE_AGY_MODELS=str(rich_models))

    # 1. Metin çıktısı (TR)
    res_tr = run_ajan(["modeller"], env=env)
    assert res_tr.returncode == 0, res_tr.stderr
    out_tr = res_tr.stdout
    assert "Varsayılan: gemini-4-neon-xhigh (neon)" in out_tr
    assert "Orkestratör:" in out_tr
    assert out_tr.index("Gemini aileleri:") < out_tr.index("Orkestratör:")
    assert (
        "  gemini-pro-orchestrator-neon  (Orchestrator (Neon))  "
        "[orkestra, orchestrator, orkestra-neon, orchestrator-neon]"
    ) in out_tr
    assert (
        "  gemini-pro-orchestrator-g1-pro  (Orchestrator (Argon))  "
        "[orkestra-g1-pro, orchestrator-g1-pro, orkestra-argon, orchestrator-argon]"
    ) in out_tr

    # Diğer Gemini modelleri altında orkestratör olmamalı, gemini-2.5-pro-preview olmalı
    assert "Diğer Gemini modelleri" in out_tr
    other_part = out_tr.split("Diğer Gemini modelleri", 1)[1]
    assert "gemini-2.5-pro-preview" in other_part
    assert "gemini-pro-orchestrator-neon" not in other_part
    assert "gemini-pro-orchestrator-g1-pro" not in other_part

    # 2. Metin çıktısı (EN)
    env_en = dict(env, AJAN_DIL="en")
    res_en = run_ajan(["models"], env=env_en)
    assert res_en.returncode == 0, res_en.stderr
    assert "Orchestrators:" in res_en.stdout
    assert "Orkestratör:" not in res_en.stdout
    other_part_en = res_en.stdout.split("Other Gemini models", 1)[1]
    assert "gemini-pro-orchestrator-neon" not in other_part_en
    assert "gemini-pro-orchestrator-g1-pro" not in other_part_en

    # 3. JSON çıktısı: mevcut anahtarlar korunmuş + yeni 'orkestra' anahtarı
    res_json = run_ajan(["modeller", "--json"], env=env)
    assert res_json.returncode == 0, res_json.stderr
    data = json.loads(res_json.stdout)
    assert data["varsayilan"] == "gemini-4-neon-xhigh"
    assert data["varsayilan_aile"] == "neon"
    assert all(
        "orchestrator" not in k and "orkestra" not in k
        for k in data["takma_adlar"]
    )
    assert len(data["modeller"]) == 6
    assert data["orkestra"]["takma_adlar"] == {
        "orkestra": "gemini-pro-orchestrator-neon",
        "orchestrator": "gemini-pro-orchestrator-neon",
        "orkestra-neon": "gemini-pro-orchestrator-neon",
        "orchestrator-neon": "gemini-pro-orchestrator-neon",
        "orkestra-g1-pro": "gemini-pro-orchestrator-g1-pro",
        "orchestrator-g1-pro": "gemini-pro-orchestrator-g1-pro",
        "orkestra-argon": "gemini-pro-orchestrator-g1-pro",
        "orchestrator-argon": "gemini-pro-orchestrator-g1-pro",
    }
    assert data["orkestra"]["modeller"] == [
        {
            "id": "gemini-pro-orchestrator-neon",
            "ad": "Orchestrator (Neon)",
            "sonek": "neon",
            "takma_adlar": [
                "orkestra",
                "orchestrator",
                "orkestra-neon",
                "orchestrator-neon",
            ],
        },
        {
            "id": "gemini-pro-orchestrator-g1-pro",
            "ad": "Orchestrator (Argon)",
            "sonek": "g1-pro",
            "takma_adlar": [
                "orkestra-g1-pro",
                "orchestrator-g1-pro",
                "orkestra-argon",
                "orchestrator-argon",
            ],
        },
    ]

    # 4. Orkestratörsüz katalog: bölüm basılmaz, JSON 'orkestra' anahtarı boş döner
    no_orch_models = tmp_path / "models_without_orch.txt"
    no_orch_models.write_text(
        "Fetching available models...\n"
        "gemini-4-neon-xhigh\tGemini 4 Neon (XHigh)\n"
        "claude-opus-5-5-high\tClaude Opus 5.5 (High)\n",
        encoding="utf-8",
    )
    env_no_orch = dict(test_env["env"], FAKE_AGY_MODELS=str(no_orch_models))

    res_no_txt = run_ajan(["modeller", "--yenile"], env=env_no_orch)
    assert res_no_txt.returncode == 0, res_no_txt.stderr
    assert "Orkestratör:" not in res_no_txt.stdout
    assert "Orchestrators:" not in res_no_txt.stdout

    res_no_en = run_ajan(
        ["models"], env=dict(env_no_orch, AJAN_DIL="en")
    )
    assert res_no_en.returncode == 0, res_no_en.stderr
    assert "Orchestrators:" not in res_no_en.stdout

    res_no_json = run_ajan(["modeller", "--json"], env=env_no_orch)
    assert res_no_json.returncode == 0, res_no_json.stderr
    data_no = json.loads(res_no_json.stdout)
    assert data_no["orkestra"] == {"takma_adlar": {}, "modeller": []}


def test_orkestrator_varsayilan_olmaz_ve_yeni_aile_bildirimi_tetiklemez(
    test_env: dict[str, Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    Orkestratörler asla otomatik varsayılan seçilmemeli (tercih edilen aileler yoksa bile
    DEFAULT_MODEL'e düşmeli) ve kataloga yalnız yeni orkestratör eklendiğinde aile bildirimi
    tetiklenmemelidir.
    """
    # 1. Katalogda neon + orkestratör -> varsayılan neon kalır
    with_neon = [
        {"id": "gemini-pro-orchestrator-neon", "ad": "Orchestrator (Neon)"},
        {"id": "gemini-pro-orchestrator-g1-pro", "ad": "Orchestrator (Argon)"},
        {"id": "gemini-4-neon-xhigh", "ad": "Gemini 4 Neon (XHigh)"},
    ]
    assert ajan.default_model(with_neon) == "gemini-4-neon-xhigh"

    # 2. Yalnız orkestratörler (neon/hydrogen/argon/flash yok) -> DEFAULT_MODEL'e düşer
    only_orch = [
        {"id": "gemini-pro-orchestrator-neon", "ad": "Orchestrator (Neon)"},
        {"id": "gemini-pro-orchestrator-g1-pro", "ad": "Orchestrator (Argon)"},
    ]
    assert ajan.default_model(only_orch) == DEFAULT_MODEL

    # 3. Kullanıcı açıkça AJAN_MODEL=orkestra verirse orkestratör seçilir
    monkeypatch.setenv("AJAN_MODEL", "orkestra")
    assert ajan.default_model(only_orch) == "gemini-pro-orchestrator-neon"
    monkeypatch.delenv("AJAN_MODEL", raising=False)

    # 4. İlk önbellek sonrası kataloga yalnız yeni bir orkestratör eklendiğinde stderr sessiz
    base_models = tmp_path / "models_orch_base.txt"
    base_models.write_text(
        "Fetching available models...\n"
        "gemini-4-neon-xhigh\tGemini 4 Neon (XHigh)\n"
        "gemini-pro-orchestrator-neon\tOrchestrator (Neon)\n",
        encoding="utf-8",
    )
    env_base = dict(test_env["env"], FAKE_AGY_MODELS=str(base_models))
    res_init = run_ajan(["modeller", "--json"], env=env_base)
    assert res_init.returncode == 0, res_init.stderr
    assert res_init.stderr.strip() == ""

    with_new_orch = tmp_path / "models_orch_added.txt"
    with_new_orch.write_text(
        base_models.read_text(encoding="utf-8")
        + "gemini-pro-orchestrator-g1-pro\tOrchestrator (Argon)\n"
        + "gemini-pro-orchestrator-beta\tOrchestrator (Beta)\n",
        encoding="utf-8",
    )
    env_added = dict(test_env["env"], FAKE_AGY_MODELS=str(with_new_orch))
    res_refresh = run_ajan(["modeller", "--yenile", "--json"], env=env_added)
    assert res_refresh.returncode == 0, res_refresh.stderr
    assert res_refresh.stderr.strip() == ""
    data_ref = json.loads(res_refresh.stdout)
    assert data_ref["varsayilan"] == "gemini-4-neon-xhigh"
    assert (
        data_ref["orkestra"]["takma_adlar"]["orkestra-g1-pro"]
        == "gemini-pro-orchestrator-g1-pro"
    )
    assert (
        data_ref["orkestra"]["takma_adlar"]["orkestra-beta"]
        == "gemini-pro-orchestrator-beta"
    )

