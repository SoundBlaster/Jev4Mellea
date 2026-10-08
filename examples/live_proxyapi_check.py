"""Opt-in ProxyAPI smoke check: one mixed request, no semantic quality claim."""

import argparse
import json
import os
import sys
import time
from dataclasses import asdict

from mellea_jev import ChoiceQuestion, JevError, NoulQuestion, ScoreQuestion
from mellea_jev.providers.proxyapi import DEFAULT_MODEL, ProxyAPIProvider


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live", action="store_true", help="Permit one potentially billable request"
    )
    parser.add_argument("--model", default=DEFAULT_MODEL)
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to permit a potentially billable request.")
    key = os.environ.get("PROXYAPI_API_KEY", "")
    if not key:
        parser.error("Set PROXYAPI_API_KEY first.")
    questions = {
        "is_bug": NoulQuestion(
            "Сообщает ли клиент об ошибке в продукте?",  # noqa: RUF001
            {
                "true": "Клиент описывает сломанное или неожиданное поведение продукта.",
                "false": "Клиент задаёт вопрос или просит новую функцию.",
            },
        ),
        "team": ChoiceQuestion(
            "Какая команда должна взять этот тикет?",
            {
                "account": "Вход, права доступа или профиль.",
                "frontend": "Отображение, вёрстка или совместимость с браузерами.",  # noqa: RUF001
                "payments": "Оформление заказа, биллинг или обработка платежей.",
            },
        ),
        "urgency": ScoreQuestion(
            "Насколько срочен этот тикет?",
            [
                "Может подождать следующего релиза",
                "Нужно исправить на этой неделе",
                "Прямо сейчас блокирует выручку",
            ],
        ),
    }
    start = time.monotonic()
    try:
        with ProxyAPIProvider(api_key=key, model=args.model) as provider:
            result = provider.system_one(
                state={
                    "customer_tier": "enterprise",
                    "ticket": "После нажатия «Оплатить» страница оформления заказа становится "
                    "пустой. Пробовал в двух браузерах.",
                },
                questions=questions,
            )
    except (JevError, ValueError) as exc:
        print(f"Check did not complete: {exc}", file=sys.stderr)
        return 3
    report = {
        "outcome": "pass",
        "scope": "API contract only; no semantic quality or latency SLA claim",
        "elapsed_seconds": round(time.monotonic() - start, 3),
        "model": result.model,
        "request_id": result.request_id,
        "usage": asdict(result.usage) if result.usage else None,
        "answers": {name: asdict(answer) for name, answer in result.answers.items()},
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
