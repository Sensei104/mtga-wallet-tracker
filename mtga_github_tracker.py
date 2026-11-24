import argparse
import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path

DEFAULT_LOG_PATH = Path(
    os.path.expandvars(r"%USERPROFILE%\AppData\LocalLow\Wizards Of The Coast\MTGA\Player.log")
)
REPO_ROOT = Path(__file__).resolve().parent
WALLET_JSON_PATH = REPO_ROOT / "docs" / "wallet.json"
REPO_URL = "https://github.com/Sensei104/mtga-wallet-tracker.git"


def parse_log(log_path: Path) -> dict:
    if not log_path.exists():
        raise FileNotFoundError(f"File di log non trovato: {log_path}")

    text = log_path.read_text(encoding="utf-8", errors="replace")

    account = None
    # 1. Cerca la riga esatta di login di MTGA
    login_matches = re.findall(
        r"\[Accounts - Login\]\s*Logged in successfully\.\s*Display Name:\s*([^\r\n]+)",
        text,
    )
    if login_matches:
        account = login_matches[-1].strip()

    # 2. Fallback sui pattern JSON se la riga sopra non è presente
    if not account:
        for pattern in [
            r'"displayName"\s*:\s*"([^"]+)"',
            r'"playerName"\s*:\s*"([^"]+)"',
            r'"screenName"\s*:\s*"([^"]+)"',
            r'"AccountName"\s*:\s*"([^"]+)"',
            r'"accountId"\s*:\s*"([^"]+)"',
        ]:
            matches = re.findall(pattern, text)
            if matches:
                account = matches[-1].strip()
                break

    gold = None
    gems = None

    for g_pat in [
        r'"gold"\s*:\s*(\d+)',
        r'"Gold"\s*:\s*(\d+)',
        r'"goldTotal"\s*:\s*(\d+)',
    ]:
        g_matches = re.findall(g_pat, text)
        if g_matches:
            gold = int(g_matches[-1])
            break

    for d_pat in [
        r'"gems"\s*:\s*(\d+)',
        r'"Gems"\s*:\s*(\d+)',
        r'"gemsTotal"\s*:\s*(\d+)',
    ]:
        d_matches = re.findall(d_pat, text)
        if d_matches:
            gems = int(d_matches[-1])
            break

    return {
        "account": account or "UnknownAccount",
        "gold": gold,
        "gems": gems,
    }


def load_wallet(path: Path) -> dict:
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("last_updated", None)
                data.setdefault("active_account", None)
                data.setdefault("accounts", {})
                return data
        except json.JSONDecodeError:
            pass
    return {"last_updated": None, "active_account": None, "accounts": {}}


def update_wallet(wallet_path: Path, parsed: dict) -> bool:
    wallet_path.parent.mkdir(parents=True, exist_ok=True)
    data = load_wallet(wallet_path)

    account = parsed["account"]
    accounts = data["accounts"]
    existing = accounts.get(account, {})

    new_gold = parsed["gold"] if parsed["gold"] is not None else existing.get("gold", 0)
    new_gems = parsed["gems"] if parsed["gems"] is not None else existing.get("gems", 0)

    changed = (
        existing.get("gold") != new_gold
        or existing.get("gems") != new_gems
        or data.get("active_account") != account
    )

    now_iso = dt.datetime.now().astimezone().isoformat(timespec="seconds")

    accounts[account] = {
        "gold": new_gold,
        "gems": new_gems,
        "updated_at": now_iso,
    }
    data["active_account"] = account
    data["last_updated"] = now_iso

    wallet_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return changed


def run_git(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def git_push_wallet(account: str) -> None:
    status = run_git(["status", "--porcelain", "docs/wallet.json"])
    if not status.stdout.strip():
        print("Nessuna modifica in docs/wallet.json da inviare.")
        return

    add_res = run_git(["add", "docs/wallet.json"])
    if add_res.returncode != 0:
        raise RuntimeError(f"git add fallito: {add_res.stderr.strip()}")

    msg = f"Update wallet for {account} ({dt.datetime.now().strftime('%Y-%m-%d %H:%M')})"
    commit_res = run_git(["commit", "-m", msg])
    if commit_res.returncode != 0:
        raise RuntimeError(f"git commit fallito: {commit_res.stderr.strip()}")

    push_res = run_git(["push", REPO_URL, "HEAD:main"])
    if push_res.returncode != 0:
        raise RuntimeError(f"git push fallito: {push_res.stderr.strip()}")

    print("Push completato su GitHub.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggiorna docs/wallet.json da MTGA Player.log e fa push su GitHub.")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG_PATH, help="Percorso del file Player.log")
    parser.add_argument("--no-push", action="store_true", help="Aggiorna solo il file locale senza eseguire git push")
    args = parser.parse_args()

    parsed = parse_log(args.log)
    print(f"Rilevato -> Account: {parsed['account']} | Gold: {parsed['gold']} | Gems: {parsed['gems']}")

    if parsed["gold"] is None and parsed["gems"] is None:
        print("Attenzione: non ho trovato valori di Gold o Gems nel log. Verifica che 'Detailed Logs' sia attivo in MTGA.")
        return

    update_wallet(WALLET_JSON_PATH, parsed)
    print(f"Aggiornato: {WALLET_JSON_PATH}")

    if not args.no_push:
        git_push_wallet(parsed["account"])


if __name__ == "__main__":
    main()