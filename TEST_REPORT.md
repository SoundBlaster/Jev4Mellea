# Отчёт о проверке — 17 сентября 2026 года

## Фактически выполнено

Среда сборки: Python 3.13.5, Linux, HTTPX 0.28.1,
pytest 9.0.2, setuptools 82.0.1.

- Установка собственного пакета: `python -m pip install --no-deps --no-build-isolation -e .` — успешно.
- Сборка wheel: `python -m pip wheel --no-deps --no-build-isolation .` — успешно.
- `python -m compileall -q src examples tests` — успешно.
- `python examples/offline_demo.py` — успешно, три искусственных значения P(yes).
- `python -m pytest -q` — **110 passed, 2 skipped**. Полный вывод в `test-results.txt`.

Установленные HTTPX/pytest/setuptools уже были в среде. Проверка с `--no-deps`
подтверждает сборку адаптера, но не установку всех зависимостей с нуля.
Python 3.11/3.12 и macOS в этой среде отдельно не проверялись.

## Что проверено тестами

Сериализация HTTP-запроса, Bearer header, явный reference, формат Noul,
неправильные/отсутствующие поля, NaN/Infinity, неверные типы и пороги,
таймауты и HTTP-ошибки, отсутствие скрытых retries/redirects,
обработка пустого кандидата, три исхода, причины отказа и запрет выдавать
непринятый fallback. API в этих тестах заменён `httpx.MockTransport`.

`test_bridge_contract.py` проверяет наш callback с явно названными doubles
Mellea. Это НЕ доказательство выполнения настоящей Mellea.

## Что пропущено и почему

1. Модуль `test_mellea_integration.py`: настоящая Mellea не установлена;
   загрузить недостающие зависимости из сети среды сборки не удалось.
   При доступном пакете проверяется реальный `Requirement.validate`
   с тестовым контекстом и mock HTTP, без настоящего генератора.
2. `test_live_jev.py`: не задан явный opt-in `RUN_LIVE_JEV=1` с ключом.
   Никаких запросов к живому Jev в ходе проверки не сделано.

`2 skipped` — отчёт pytest: одна запись относится к пропуску всего
интеграционного модуля, другая — к одному live-тесту.

## Чего отчёт не доказывает

Сквозной путь `Mellea → Ollama → Jev → repair` не запускался.
Пример написан по опубликованным интерфейсам и исходникам тега v0.7.0.
Нюанс подавления исключений sampling также установлен чтением исходника,
а не интеграционным прогоном; см. README и API_NOTES.
Не измерялись точность Jev, калибровка вероятностей, latency, цена или
устойчивость к prompt injection. Пороги 0.90/0.10 — демонстрационная политика.

## Состав

Ядро: **276 строк** в `client.py` и `verifier.py`, включая комментарии
и пустые строки; плюс небольшой `__init__.py`. Остальное — примеры, тесты,
документация и настройки пакета. Архив не содержит ключей, зависимостей,
виртуального окружения, байткода или сборочных кэшей.

## Повторная проверка — 19 сентября 2026 года

В отдельном временном окружении Python 3.13.15 установлены собственный пакет,
`mellea==0.7.0` и `dev` dependencies. С настоящей Mellea выполнено:

- `python -m pytest -q` — **113 passed, 2 skipped**; пропущены live Jev test
  (ключ и явный opt-in) и локальный Ollama test (явный opt-in).
- Настоящий локальный цикл `Mellea → Ollama (gemma3n:e2b) → RepairTemplateStrategy`
  выполнен с Jev API через `httpx.MockTransport`: первый ответ mock отклонил,
  повторную генерацию принял, `accepted_text()` вернул проверенный результат.
- Проверено, что в mock HTTP передан reference. Запросов к TypeSafe не было.
- `RUN_LOCAL_OLLAMA=1 OLLAMA_MODEL=gemma3n:e2b python -m pytest -q
  tests/test_mellea_ollama.py` — **1 passed**.

Для повторения добавлен opt-in тест `tests/test_mellea_ollama.py`, запускаемый с
`RUN_LOCAL_OLLAMA=1` и `OLLAMA_MODEL`. Он не входит в обычный CI, поскольку там
нет локального Ollama сервера и модели. Этот тест подтверждает интеграционный
контрольный поток, но не качество Jev: его оценки заданы фикстурой.

## Choice-классификатор — повторная проверка, 19 сентября 2026 года

- `python -m pytest -q` — **133 passed, 3 skipped** в окружении Python 3.13.15
  с Mellea 0.7.0. Пропущены два opt-in live Jev smoke tests и локальный Ollama
  test без соответствующих флагов.
- Mock HTTP тесты проверяют сериализацию TypeSafe Choice criteria, разбор
  выбранного класса/confidence/probabilities и отказ на неизвестных классах,
  неполных или некорректных вероятностях.
- Настоящий Mellea `Requirement.validate` проверен с mock Choice ответами для
  принятого и отклонённого целевого класса.
- Локальный Mellea + Ollama repair test повторно прошёл: **1 passed**. Живых
  запросов к TypeSafe не выполнялось.
