"""Shopping tools implemented solely through the rendered mock storefront."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import posixpath
from pathlib import Path
import re
import socket
from threading import Thread
from time import monotonic, sleep
from urllib.parse import unquote, urlsplit

from shopping_agent.contracts import Product, ProductObservation, SearchInput, SearchResult, StoreRecord
from shopping_agent.interfaces import CartObservation
from shopping_agent.tools.api import ToolError

ROOT = Path(__file__).resolve().parents[3]
DIST = ROOT / "mock-store/storefront/dist"


def require_browser():
    if not (DIST / "index.html").is_file():
        raise ValueError("Build the storefront first: npm --prefix mock-store/storefront ci && npm --prefix mock-store/storefront run build")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ValueError("Install requirements-browser.txt, then run python -m playwright install chromium") from exc
    with sync_playwright() as playwright:
        if not Path(playwright.chromium.executable_path).is_file():
            raise ValueError("Chromium is missing; run python -m playwright install chromium")
    return sync_playwright


class BrowserTools:
    """DOM adapter; never consumes network responses or private application state."""

    def __init__(self, page, base_url, artifact_dir, on_action=None):
        from playwright.sync_api import expect
        self.page, self.base_url = page, base_url
        self.artifact_dir = Path(artifact_dir)
        self.on_action = on_action
        self.actions = []
        self.expect = expect
        self._action("navigate", base_url, lambda: page.goto(base_url))
        self.expect(page.get_by_test_id("storefront-state")).to_have_attribute("data-ready", "true")
        self._ready()
        self.mode = page.get_by_test_id("storefront-state").get_attribute("data-mode")

    def _action(self, kind, target, operation):
        event = {"sequence": len(self.actions) + 1, "kind": kind, "target": target,
                 "duration_seconds": 0, "error": None}
        self.actions.append(event)
        if self.on_action:
            self.on_action(event)
        start = monotonic()
        try:
            return operation()
        except Exception as exc:
            event["error"] = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            event["duration_seconds"] = monotonic() - start
            # Actions are persisted even if the worker is stopped mid-trial.
            pending = self.artifact_dir / "actions.tmp"
            pending.write_text(json.dumps(self.actions, indent=2))
            pending.replace(self.artifact_dir / "actions.json")
            if self.on_action:
                self.on_action(event)

    def _ready(self):
        self.expect(self.page.get_by_test_id("storefront-state")).to_have_attribute("data-busy", "false")
        alerts = self.page.get_by_role("alert")
        if alerts.count():
            message = alerts.first.inner_text()
            status = 409 if "insufficient stock" in message.casefold() else None
            raise ToolError(message, status)

    def _ui(self, kind, locator, value=None, fetch=False):
        revision = self.page.get_by_test_id("storefront-state").get_attribute("data-revision")
        if kind == "click":
            op = locator.click
        elif kind == "fill":
            op = lambda: locator.fill(value)
        else:
            op = lambda: locator.select_option(str(value))
        def perform():
            op()
            if fetch:
                self.expect(self.page.get_by_test_id("storefront-state")).not_to_have_attribute("data-revision", revision)
            self._ready()
        self._action(kind, str(locator), perform)

    def _close_cart(self):
        close = self.page.get_by_role("button", name="Close bag", exact=True)
        if close.count():
            self._ui("click", close)

    def _directory(self):
        self._close_cart()
        self._ui("click", self.page.get_by_role("button", name="Browse stores", exact=True))

    @staticmethod
    def _field(root, field):
        return root.locator(f'[data-field="{field}"]').inner_text().strip()

    def list_stores(self):
        if self.mode == "flat":
            raise ToolError("This storefront has no store directory", 404)
        self._directory()
        def read():
            return [StoreRecord(store_id=self._field(card, "store_id"),
                                name=card.locator("h2").inner_text(),
                                brand_seller=self._field(card, "brand_seller"),
                                notes=self._field(card, "notes") or None)
                    for card in self.page.get_by_test_id("store-card").all()]
        return self._action("read_dom", "store directory", read)

    def _choose_store(self, store_id):
        self._close_cart()
        if self.mode == "flat":
            if store_id:
                raise ToolError("Flat storefront does not have store IDs", 400)
            back = self.page.get_by_role("button", name="← Back to results", exact=True)
            if back.count():
                self._ui("click", back)
            return
        if not store_id:
            raise ToolError("store_id is required in multi-store mode", 400)
        self._directory()
        for card in self.page.get_by_test_id("store-card").all():
            if self._field(card, "store_id") == store_id:
                self._ui("click", card.get_by_role("button"), fetch=True)
                return
        raise ToolError("Unknown store", 404)

    def _card(self, identity):
        for card in self.page.get_by_test_id("result-card").all():
            listing = card.locator('[data-field="listing_id"]')
            key = listing.inner_text().strip() if listing.count() else self._field(card, "product_id")
            if key == identity:
                return card
        return None

    def _read_listing(self):
        def read():
            root = self.page.get_by_test_id("listing-facts")
            fields = {name: self._field(root, name) for name in (
                "product_id", "listing_id", "store_id", "title", "description", "category",
                "price", "currency", "stock", "seller", "sponsored")}
            attributes = {}
            for item in root.locator("[data-attribute]").all():
                key, value = item.get_attribute("data-attribute"), item.inner_text().strip()
                if value in {"true", "false"}:
                    value = value == "true"
                elif key != "size" and re.fullmatch(r"-?\d+(?:\.\d+)?", value):
                    value = float(value) if "." in value else int(value)
                attributes[key] = value
            reviews = [{"review_id": self._field(row, "review_id"),
                        "rating": int(self._field(row, "rating")), "text": self._field(row, "text")}
                       for row in root.get_by_test_id("listing-review").all()]
            product = Product(product_id=fields["product_id"], title=fields["title"],
                              description=fields["description"], category=fields["category"],
                              price=float(fields["price"]), currency=fields["currency"],
                              stock=int(fields["stock"]), seller=fields["seller"],
                              sponsored=fields["sponsored"] == "true", attributes=attributes, reviews=reviews)
            return ProductObservation(product=product, listing_id=fields["listing_id"] or None,
                                      store_id=fields["store_id"] or None, source_url=self.page.url,
                                      observed_at=datetime.now(timezone.utc))
        return self._action("read_dom", "listing facts and reviews", read)

    def search(self, inputs: SearchInput):
        self._choose_store(inputs.store_id)
        self._ui("click", self.page.get_by_role("button", name="Clear filters", exact=True))
        self._ui("fill", self.page.get_by_label("Search", exact=True), inputs.query)
        self._ui("click", self.page.get_by_role("button", name="Search", exact=True), fetch=True)
        identities = []
        for card in self.page.get_by_test_id("result-card").all()[:inputs.max_results]:
            listing = card.locator('[data-field="listing_id"]')
            identities.append(listing.inner_text().strip() if listing.count() else self._field(card, "product_id"))
        observations = []
        for identity in identities:
            self._ui("click", self._card(identity).get_by_test_id("open-listing"), fetch=True)
            observations.append(self._read_listing())
            self._ui("click", self.page.get_by_role("button", name="← Back to results", exact=True))
        return SearchResult(items=observations, query=inputs.query)

    def get_listing(self, product_id=None, *, store_id=None, listing_id=None):
        if listing_id:
            parsed_store, _, parsed_product = listing_id.partition(":")
            store_id, product_id = parsed_store, parsed_product
        if not product_id:
            raise ToolError("product_id or listing_id is required", 400)
        self._choose_store(store_id)
        identity = listing_id or (f"{store_id}:{product_id}" if store_id else product_id)
        card = self._card(identity)
        if card is None:
            # A requested listing need not occur in the last search's result set.
            self._ui("fill", self.page.get_by_label("Search", exact=True), "")
            self._ui("click", self.page.get_by_role("button", name="Search", exact=True), fetch=True)
            card = self._card(identity)
        if card is None:
            raise ToolError("Listing not found in the visible store catalog", 404)
        self._ui("click", card.get_by_test_id("open-listing"), fetch=True)
        return self._read_listing()

    def inspect_cart(self):
        self._close_cart()
        self._ui("click", self.page.get_by_role("button", name="Open bag", exact=True), fetch=True)
        def read():
            dialog = self.page.get_by_role("dialog")
            items = []
            for row in dialog.get_by_test_id("cart-line").all():
                item = {key: self._field(row, key) for key in (
                    "product_id", "store_id", "listing_id", "quantity", "unit_price", "line_total", "in_stock")}
                item.update(quantity=int(item["quantity"]), unit_price=float(item["unit_price"]),
                            line_total=float(item["line_total"]), in_stock=item["in_stock"] == "true")
                item["store_id"], item["listing_id"] = item["store_id"] or None, item["listing_id"] or None
                items.append(item)
            return CartObservation(items=items, total=float(dialog.get_by_test_id("cart-total").inner_text()),
                                   currency=dialog.get_by_test_id("cart-currency").inner_text(),
                                   source_url=self.page.url, observed_at=datetime.now(timezone.utc).isoformat())
        return self._action("read_dom", "bag contents", read)

    def add_to_cart(self, selection):
        self.get_listing(selection.product_id, store_id=selection.store_id, listing_id=selection.listing_id)
        add = self.page.get_by_role("button", name="Add selected listing to bag", exact=True)
        if not add.is_enabled():
            raise ToolError("Listing is unavailable", 409)
        if selection.quantity > 5:
            raise ToolError("Visible quantity selector supports at most five units", 400)
        self._ui("select", self.page.get_by_label("Quantity", exact=True), selection.quantity)
        self._ui("click", add, fetch=True)
        return self.inspect_cart()


@contextmanager
def browser_session(app, artifact_dir, *, headed=False, on_action=None):
    """Serve the same evaluator-owned store instance and the built UI on one origin."""
    sync_playwright = require_browser()
    import uvicorn
    from starlette.staticfiles import StaticFiles

    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    app.mount("/", StaticFiles(directory=DIST, html=True), name="storefront")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    browser = context = None
    base_url = f"http://127.0.0.1:{port}"
    try:
        deadline = monotonic() + 15
        while not server.started:
            if not thread.is_alive() or monotonic() >= deadline:
                raise RuntimeError("Browser trial server did not start")
            sleep(.01)
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=not headed)
                context = browser.new_context(service_workers="block", viewport={"width": 1440, "height": 1000})
                origin = urlsplit(base_url)
                def guard(route):
                    url = urlsplit(route.request.url)
                    path = posixpath.normpath(unquote(url.path))
                    allowed = (url.scheme, url.netloc) == (origin.scheme, origin.netloc)
                    allowed = allowed and not path.startswith(("/internal", "/docs", "/openapi"))
                    allowed = allowed and not (route.request.is_navigation_request() and path.startswith("/api"))
                    route.continue_() if allowed else route.abort()
                context.route("**/*", guard)
                context.tracing.start(screenshots=True, snapshots=True)
                page = context.new_page()
                page.set_default_timeout(5000)
                adapter = BrowserTools(page, base_url, artifact_dir, on_action)
                adapter.browser_version = browser.version
                yield adapter
            finally:
                if context:
                    try:
                        if context.pages:
                            context.pages[0].screenshot(path=str(artifact_dir / "final.png"), full_page=True, timeout=3000)
                        context.tracing.stop(path=str(artifact_dir / "trace.zip"))
                    finally:
                        try:
                            context.close()
                        finally:
                            if browser:
                                browser.close()
                elif browser:
                    browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
