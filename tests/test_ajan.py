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


@pytest.fixture(autouse=True)
def isolate_defaults(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """
    Tüm testler için varsayılan ortamı izole eder.
    Gerçek ~/.gemini ve ~/.local/state/ajan dizinlerine erişimi tamamen engeller.
    """
    temp_dir = tmp_path_factory.mktemp("safe_default")
    safe_state = temp_dir / "safe_state"
    safe_settings = temp_dir / "gemini" / "settings.json"
    safe_state.mkdir(parents=True, exist_ok=True)
    safe_settings.parent.mkdir(parents=True, exist_ok=True)
    safe_settings.write_text(
        json.dumps({"permissions": {"allow": []}}), encoding="utf-8"
    )

    monkeypatch.setenv("AJAN_DIZIN", str(safe_state))
    monkeypatch.setenv("AJAN_AYAR", str(safe_settings))
    monkeypatch.setenv("AJAN_DIL", "tr")


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
    log_file = tmp_path / "fake_agy.log"
    script_file = tmp_path / "fake_agy.py"

    code = f"""#!/usr/bin/env python3
import json
import os
import sys
import time

log_file = {repr(str(log_file))}
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
    return str(script_file), str(log_file)


@pytest.fixture
def test_env(tmp_path: Any, fake_agy: tuple[str, str]) -> dict[str, Any]:
    """Testler için yalıtılmış ortam ve dizinleri hazırlar."""
    fake_bin, log_path = fake_agy
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

    return {
        "env": env,
        "state_dir": state_dir,
        "settings_path": settings_path,
        "log_path": log_path,
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
    assert DEFAULT_MODEL == "gemini-4-hydrogen-xhigh"
    assert resolve_model("flash") == "gemini-3.8-flash-high"
    assert resolve_model("flash-orta") == "gemini-3.8-flash-medium"
    assert resolve_model("argon") == "gemini-4-argon-high"
    assert resolve_model("argon-orta") == "gemini-4-argon-medium"
    assert resolve_model("hydrogen") == "gemini-4-hydrogen-xhigh"
    assert resolve_model("hydrogen-high") == "gemini-4-hydrogen-high"
    assert resolve_model("hydrogen-orta") == "gemini-4-hydrogen-medium"
    assert resolve_model(None) == "gemini-4-hydrogen-xhigh"
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
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    """
    (a) save_meta benzersiz geçici dosya kullanmalı.
    (b) cmd_baslat ve calistir_devam bekçi başlatıldıktan sonra meta.json'u yeniden okuyup
        yalnız bekci_pid'i güncellemeli; calistir_devam pid=None atamasını bekçiden önce yapmalı.
    """
    state_dir = tmp_path / "state"
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"permissions": {"allow": []}}), encoding="utf-8")
    monkeypatch.setenv("AJAN_DIZIN", str(state_dir))
    monkeypatch.setenv("AJAN_AYAR", str(settings_path))

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


def test_varsayilan_model_cli_uzerinden_hydrogen(test_env: dict[str, Any]) -> None:
    """--model verilmediğinde agy CLI'a varsayılan gemini-4-hydrogen-xhigh aktarılmalıdır."""
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
    assert argv[m_idx + 1] == "gemini-4-hydrogen-xhigh"
