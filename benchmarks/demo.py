"""Verify the Atlas demo with real Keycloak accounts in a local Chrome session."""

import argparse
import csv
import json
import os
import sqlite3
from contextlib import closing
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright


BASE = "http://localhost:8000"
PRIORITY = "Quelle est la priorité de mon département pour le projet Atlas ?"
RESERVE = "Quel est le montant de la réserve budgétaire du projet Atlas ?"
RESERVE_PATH = BASE + "/api/v1/documents/finance-01-confidentiel"
SCENARIOS = {
    "finance": (("priority", PRIORITY, "finance-01-interne", "10800 MAD"), ("reserve", RESERVE, None, "")),
    "informatique": (("priority", PRIORITY, "informatique-01-interne", "4 scénarios"),),
    "direction": (("reserve", RESERVE, "finance-01-confidentiel", "1150 MAD"),),
}


def password_for_demo():
    value = os.getenv("PFA_DEMO_PASSWORD")
    if value:
        return value
    for line in Path(".env").read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "PFA_DEMO_PASSWORD":
            return value.strip().strip("'\"")
    raise ValueError("Set PFA_DEMO_PASSWORD in the local .env")


def login(page, account, password):
    page.goto(BASE, wait_until="networkidle")
    with page.expect_request(lambda request: "/openid-connect/auth?" in request.url) as seen:
        page.get_by_role("button", name="Se connecter", exact=True).click()
    params = parse_qs(urlsplit(seen.value.url).query)
    assert params["response_type"] == ["code"] and params["code_challenge_method"] == ["S256"]
    page.locator("#username").fill(account)
    page.locator("#password").fill(password)
    with page.expect_request(lambda request: request.url == BASE + "/api/v1/me") as identity:
        page.locator("#kc-login").click()
    return identity.value.header_value("authorization")


def ask(page, question, strategy):
    page.get_by_label("Question").fill(question)
    page.get_by_label("Stratégie").select_option(strategy)
    with page.expect_response(lambda response: response.url == BASE + "/api/v1/answers") as seen:
        page.get_by_role("button", name="Répondre", exact=True).click()
    response = seen.value
    assert response.status == 200, response.status
    data = response.json()
    expect(page.locator("#answer-text")).to_have_text(data["answer"])
    expect(page.get_by_role("button", name="Répondre", exact=True)).to_be_enabled()
    timing = response.request.timing
    assert timing["responseEnd"] >= timing["requestStart"] >= 0
    return data, round(timing["responseEnd"] - timing["requestStart"], 3)


def audit_case(database, response, role, question, strategy, acl):
    with closing(sqlite3.connect(database)) as connection:
        event = connection.execute(
            "SELECT operation, roles, question, strategy, context_ids, citation_ids, result, total_ms, model_ms "
            "FROM access_events WHERE request_id=?", (response["request_id"],),
        ).fetchone()
    operation, roles, recorded_question, recorded_strategy, context, cited, status, total, model = event
    assert (operation, json.loads(roles), recorded_question, recorded_strategy) == ("answer", [role], question, strategy)
    context_ids, citation_ids = json.loads(context), json.loads(cited)
    assert status == response["status"]
    assert citation_ids == [citation["document_id"] for citation in response["citations"]]
    assert set(citation_ids) <= set(context_ids)
    assert all(role in acl[document_id] for document_id in context_ids)
    assert total >= model >= 0
    return len(context_ids), total, model


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--audit-db", type=Path, default=Path(".pfa-state/access.sqlite3"))
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    password = password_for_demo()
    acl = {}
    for line in Path("data/corpus.jsonl").read_text(encoding="utf-8").splitlines():
        document = json.loads(line)
        acl[document["id"]] = document["allowed_roles"]
    rows = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(channel="chrome", headless=True)
            with browser.new_context(viewport={"width": 390, "height": 844}) as context:
                page = context.new_page()
                page.set_default_timeout(120000)
                assert context.request.get(BASE + "/readyz").status == 200
                assert context.request.get(RESERVE_PATH).status == 401
                for role, scenarios in SCENARIOS.items():
                    token = login(page, f"demo-{role}", password)
                    expect(page.locator("#identity")).to_have_text(f"demo-{role} · {role}")
                    direct = context.request.get(RESERVE_PATH, headers={"Authorization": token})
                    assert direct.status == (200 if role == "direction" else 404)
                    if role == "finance":
                        ask(page, PRIORITY, "pre_filter")
                    for label, question, gold, expected_excerpt in scenarios:
                        for repetition in range(1, args.repeats + 1):
                            methods = ("pre_filter", "post_filter") if repetition % 2 else ("post_filter", "pre_filter")
                            for method in methods:
                                data, http_ms = ask(page, question, method)
                                citations = [item["document_id"] for item in data["citations"]]
                                if gold:
                                    assert data["status"] == "answered" and gold in citations
                                    assert expected_excerpt in data["answer"]
                                else:
                                    assert data["status"] == "insufficient_evidence" and not citations
                                count, app_ms, model_ms = audit_case(
                                    args.audit_db, data, role, question, method, acl,
                                )
                                rows.append({
                                    "role": role, "scenario": label, "strategy": method,
                                    "repetition": repetition, "status": data["status"],
                                    "citations": "|".join(citations), "context_documents": count,
                                    "http_ms": http_ms, "application_ms": app_ms, "generation_ms": model_ms,
                                })
                        if gold:
                            page.locator("#sources button").first.click()
                            expect(page.locator("#document-text")).to_contain_text(expected_excerpt)
                    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                    page.get_by_role("button", name="Se déconnecter", exact=True).click()
                    expect(page.get_by_role("button", name="Se connecter", exact=True)).to_be_visible()
                    expect(page.locator("#answer")).to_be_hidden()

                token = login(page, "demo-sans-role", password)
                expect(page.locator("#status")).to_contain_text("aucun rôle")
                assert context.request.get(BASE + "/api/v1/me", headers={"Authorization": token}).status == 403
            browser.close()
    except Exception as error:
        parser.exit(1, (str(error) or type(error).__name__).replace(password, "[redacted]") + "\n")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    print(f"Verified {len(rows)} signed answer requests, their access journal records, and account switching.")


if __name__ == "__main__":
    main()
