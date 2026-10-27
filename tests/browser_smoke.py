"""Optional browser check: python tests/browser_smoke.py (requires Playwright/Chromium).

Starts an isolated application with a temporary database and simulated external APIs.
Never connects to a personal Navidrome server. Screenshots contain test fixtures.
"""
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def serve(port):
    import httpx
    import uvicorn
    from conftest import FakeNavidrome, PASSWORD
    from app.main import create_app
    with tempfile.TemporaryDirectory(prefix="playlistr-browser-") as data_dir:
        remote = FakeNavidrome()
        client = httpx.AsyncClient(transport=httpx.MockTransport(remote.handle))
        app = create_app(data_dir, PASSWORD, client)
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


def check():
    from playwright.sync_api import sync_playwright, expect
    from conftest import NAV_PASSWORD, PASSWORD
    with socket.socket() as available:
        available.bind(("127.0.0.1", 0))
        port = available.getsockname()[1]
    server = subprocess.Popen([sys.executable, __file__, "--serve", str(port)], cwd=ROOT)
    url = f"http://127.0.0.1:{port}"
    output = Path(os.environ.get("PLAYLISTR_SCREENSHOTS", "/tmp/playlistr-screenshots"))
    output.mkdir(parents=True, exist_ok=True)
    try:
        for _ in range(100):
            try:
                urllib.request.urlopen(url + "/healthz", timeout=1)
                break
            except OSError:
                time.sleep(.1)
        else:
            raise AssertionError("Browser test server failed to start")
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=os.environ.get("PLAYLISTR_BROWSER_BINARY") or None,
                args=["--no-sandbox"])
            context = browser.new_context(viewport={"width":1440,"height":1100})
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(url)
            page.get_by_label("Contraseña de Playlistr").fill(PASSWORD)
            page.get_by_role("button", name="Entrar a mi biblioteca").click()
            expect(page.get_by_role("heading", name="Crea tu próxima favorita")).to_be_visible()
            page.get_by_role("button", name="Conectar servidor").click()
            page.get_by_label("Dirección del servidor").fill("http://navidrome.test")
            page.get_by_label("Usuario de Navidrome").fill("listener")
            page.get_by_label("Contraseña de Navidrome", exact=True).fill(NAV_PASSWORD)
            page.get_by_role("button", name="Probar conexión y guardar").click()
            expect(page.get_by_text("Navidrome configurado", exact=True)).to_be_visible()
            page.get_by_role("button", name="Sincronizar biblioteca", exact=False).click()
            expect(page.locator("#job-banner")).to_be_visible()
            expect(page.locator("#job-banner")).to_be_hidden(timeout=15000)
            page.locator('nav [data-page="artists"]').click()
            page.get_by_role("button", name="Buscar pendientes").click()
            expect(page.get_by_text("Fuente verificada", exact=True)).to_be_visible(timeout=15000)
            page.locator('[data-artist="a1"]').click()
            expect(page.get_by_role("link", name="MusicBrainz")).to_be_visible()
            page.get_by_role("button", name="Cerrar", exact=True).click()
            page.locator('nav [data-page="create"]').click()
            page.get_by_label("Nombre de la playlist").fill("Prueba de navegador")
            page.locator('[data-genre="art rock"]').click()
            page.get_by_role("button", name="Generar vista previa").click()
            expect(page.locator(".track")).to_have_count(2)
            expect(page.locator(".track-name").first).to_contain_text("Radiohead")
            page.locator(".track-remove").first.click()
            expect(page.locator(".track")).to_have_count(1)
            expect(page.locator(".preview-summary").first).to_contain_text("1 canciones")
            page.evaluate("window.scrollTo(0, 0)")
            expect(page.locator("#toast")).to_be_hidden(timeout=10000)
            page.screenshot(path=str(output / "desktop.png"), full_page=True)
            page.get_by_role("button", name="Guardar en Navidrome").click()
            expect(page.locator(".playlist-card h3")).to_have_text("Prueba de navegador")
            expect(page.locator(".playlist-card")).to_contain_text("1 canciones")
            # Persistent login, mobile layout, manual classification, and logout.
            page.reload()
            expect(page.get_by_role("heading", name="Crea tu próxima favorita")).to_be_visible()
            page.set_viewport_size({"width":390,"height":844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), "Horizontal mobile overflow"
            page.screenshot(path=str(output / "mobile.png"), full_page=True)
            page.locator('nav [data-page="artists"]').click()
            page.locator('[data-artist="a2"]').click()
            page.get_by_label("Ajustar géneros manualmente").fill("trip hop, electronic")
            page.get_by_role("button", name="Guardar mis géneros").click()
            expect(page.locator('[data-artist="a2"]')).to_contain_text("trip hop")
            page.locator('#connection-badge').click()
            page.get_by_role("button", name="Cerrar sesión", exact=True).last.click()
            expect(page.locator("#login")).to_be_visible()
            assert errors == [], errors
            browser.close()
        print("Browser smoke passed: login, connection, sync, enrichment, sources, preview, playlist, mobile, manual edit, logout.")
        print(f"Fixture screenshots: {output}")
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        serve(int(sys.argv[2]))
    else:
        check()
