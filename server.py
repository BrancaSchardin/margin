#!/usr/bin/env python3
"""Margin — kleiner lokaler Server.

Serviert die Oberflaeche (index.html) und legt alle Eintraege in daten.json
im selben Ordner ab. Vor jedem Schreibvorgang wandert der bisherige Stand
einmal pro Tag nach sicherungen/.

Laeuft nur auf 127.0.0.1, ist also von aussen nicht erreichbar.
"""

import http.server
import json
import os
import shutil
import socketserver
import sys
import threading
import time
import webbrowser
from datetime import date
from pathlib import Path

BASE = Path(__file__).resolve().parent
DATA = BASE / "daten.json"
BACKUP_DIR = BASE / "sicherungen"
PORTS = range(8770, 8790)


def lies():
    if not DATA.exists():
        return []
    try:
        inhalt = json.loads(DATA.read_text(encoding="utf-8"))
        return inhalt if isinstance(inhalt, list) else []
    except (json.JSONDecodeError, OSError):
        return []


def sichere():
    """Tageskopie des bisherigen Standes, bevor ueberschrieben wird."""
    if not DATA.exists():
        return
    try:
        BACKUP_DIR.mkdir(exist_ok=True)
        shutil.copy2(DATA, BACKUP_DIR / f"daten-{date.today().isoformat()}.json")
    except OSError:
        pass  # eine fehlgeschlagene Sicherung darf das Speichern nicht blockieren


def schreibe(items):
    sichere()
    tmp = DATA.with_name("daten.json.tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, DATA)  # atomar: entweder alter oder neuer Stand, nie halb


def bereits_da(port):
    """Antwortet auf dem Port schon ein Bestand-Server?"""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/daten", timeout=1.5) as r:
            json.loads(r.read().decode("utf-8"))
            return True
    except Exception:
        return False


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE), **kwargs)

    def log_message(self, *args):
        pass  # keine Zugriffszeilen im Terminal

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/daten":
            return self._json(lies())
        return super().do_GET()

    def do_PUT(self):
        if self.path.split("?")[0] != "/api/daten":
            return self.send_error(404)
        try:
            laenge = int(self.headers.get("Content-Length") or 0)
            items = json.loads(self.rfile.read(laenge).decode("utf-8"))
            if not isinstance(items, list):
                raise ValueError("kein Array")
        except (ValueError, json.JSONDecodeError):
            return self._json({"ok": False, "fehler": "ungueltige Daten"}, 400)
        try:
            schreibe(items)
        except OSError as e:
            return self._json({"ok": False, "fehler": str(e)}, 500)
        return self._json({"ok": True, "anzahl": len(items)})


def binde(ports, warten):
    """Bindet den ersten freien Port.

    Im Dauerbetrieb wird gewartet statt aufgegeben — sonst wuerde launchd den
    Dienst im Sekundentakt neu starten, solange der Port noch belegt ist.
    """
    while True:
        for port in ports:
            try:
                return socketserver.ThreadingTCPServer(("127.0.0.1", port), Handler), port
            except OSError:
                continue
        if not warten:
            return None, None
        time.sleep(30)


def main():
    if not (BASE / "index.html").exists():
        print("  index.html fehlt neben server.py — Abbruch.")
        sys.exit(1)

    # --kein-fenster = Dauerbetrieb im Hintergrund (launchd): kein Browserfenster
    # beim Anmelden, und der Dienst gibt nie auf.
    dauerbetrieb = "--kein-fenster" in sys.argv
    zahlen = [a for a in sys.argv[1:] if a.isdigit()]
    ports = [int(zahlen[0])] if zahlen else list(PORTS)

    # Laeuft auf dem Standardport schon ein Bestand-Server, wird KEIN zweiter
    # gestartet — sonst wandert die Adresse und ein offenes Fenster zeigt auf
    # einen Port, den niemand mehr bedient.
    if not dauerbetrieb and not zahlen and bereits_da(PORTS.start):
        url = f"http://127.0.0.1:{PORTS.start}/"
        print()
        print(f"  Margin laeuft bereits: {url}")
        print("  Ich oeffne nur das Fenster, es wird kein zweiter Server gestartet.")
        print()
        webbrowser.open(url)
        return

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    srv, port = binde(ports, dauerbetrieb)
    if srv is None:
        print(f"  Kein freier Port gefunden ({ports[0]} …).")
        sys.exit(1)

    url = f"http://127.0.0.1:{port}/"
    print()
    print(f"  Margin laeuft:    {url}")
    print(f"  Deine Daten:     {DATA}")
    print(f"  Sicherungen:     {BACKUP_DIR}")
    print()
    if dauerbetrieb:
        print(f"  Dauerbetrieb ({time.strftime('%d.%m.%Y %H:%M')}) — laeuft im Hintergrund weiter.")
    else:
        print("  Fenster offen lassen, solange du damit arbeitest.")
        print("  Zum Beenden: Strg+C druecken oder das Fenster schliessen.")
    print(flush=True)

    if not dauerbetrieb:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n  Beendet.\n")
    finally:
        srv.server_close()


if __name__ == "__main__":
    main()
