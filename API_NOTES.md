# Проверенные внешние контракты

Дата сверки: **2026-09-19**. Это ссылки на первичные источники, а не запись
удачного live-вызова. Документация сервиса и alias модели могут измениться.

## TypeSafe

[HTTP API reference](https://docs.typesafe.ai/api) описывает:

```text
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <API_KEY>
```

Нужны `model`, `state` и именованный словарь `questions`. Адаптер задаёт
метод `system_one` передаёт именованную карту typed-вопросов и проверяет
соответствующие записи `answers` по тем же ID. Удобные `noul`, `choice` и
`score` вызывают тот же транспортный метод с одним вопросом. Дополнительные
поля ответа не требуют изменения адаптера.
`usage` не используется для решения о принятии, расчёта цены здесь нет.

[Noul](https://docs.typesafe.ai/primitives/noul) возвращает P(yes) от 0 до 1;
это не булево значение и не отдельный confidence. Значение около 0
означает уверенное «нет», а не низкую уверенность в результате «да».

[Quick start](https://docs.typesafe.ai/introduction/quickstart) подтверждает
переменную `TYPESAFE_API_KEY` и alias `jev-latest`.
[Ответы SDK](https://docs.typesafe.ai/sdk/python/api/types/responses) описывают
заголовок `x-typesafe-request-id`, который клиент переносит в метаданные.

[Choice](https://docs.typesafe.ai/primitives/choice) выбирает один класс из
фиксированного набора. В API запросе указываются `type: "choice"`,
`instructions` и `criteria` — карта меток классов с описаниями. Ответ содержит
`choice`, `probabilities` для вариантов и `confidence`. Прототип поддерживает
один Choice-вопрос на запрос, не более 255 вариантов и описания-строки либо
`null`; он проверяет, что ответ содержит ровно настроенные классы и сумма
вероятностей близка к 1. SDK также принимает более структурированные criteria,
но эта форма пока не поддержана адаптером.

[Score](https://docs.typesafe.ai/primitives/score) принимает упорядоченный
массив описаний уровней (от 2 до 10) и возвращает дробный `score`,
`probabilities` для уровней, `confidence` и `legend`. Score — это
вероятностно-взвешенная позиция на шкале, поэтому результат может быть между
двумя уровнями. Адаптер принимает строковые описания и проверяет диапазон,
распределение вероятностей, средневзвешенное значение и соответствие legend
запрошенной шкале. Структурированные описания уровней пока не поддерживаются.

[Официальный Python SDK](https://docs.typesafe.ai/sdk/python/api/clients/sync/client)
действительно имеет `TypeSafeClient.system_one(...)`; публичный метод адаптера
повторяет модель именованной карты вопросов. `jev.decide(...)`
в предыдущем обсуждении был псевдокодом. Этот маленький пакет использует
HTTP напрямую и не зависит от версии SDK.

## Mellea

Цель: `mellea==0.7.0`, Python >=3.11.

- [Write Custom Verifiers](https://docs.mellea.ai/how-to/write-custom-verifiers):
  `Requirement(description, validation_fn=...)` и `ValidationResult`.
- [Исходник ValidationResult, тег v0.7.0](https://github.com/generative-computing/mellea/blob/v0.7.0/mellea/core/requirement.py):
  контракт состоит из bool результата и необязательных `reason`, `score: float`
  и других метаданных. Jev Score адаптируется к нему как pass/fail по
  настроенному диапазону; числовой результат Jev передаётся в поле `score`.
- [Исходник Requirement, тег v0.7.0](https://github.com/generative-computing/mellea/blob/v0.7.0/mellea/core/requirement.py):
  `validate` асинхронна, но переданный callback вызывается синхронно,
  `return self.validation_fn(ctx)`. Поэтому `async def validation_fn`
  без другой точки расширения здесь не подходит.
- [Исходник SamplingResult, тег v0.7.0](https://github.com/generative-computing/mellea/blob/v0.7.0/mellea/core/sampling.py):
  `success`, `result`, `result_validations` относятся к выбранному результату.
- [BaseSamplingStrategy v0.7.0](https://github.com/generative-computing/mellea/blob/v0.7.0/mellea/stdlib/sampling/base.py):
  исключения producers пробрасываются, если ещё нет завершённых итераций.
  Если уже есть отклонённый кандидат, ошибка следующей проверки может быть
  залогирована, а вызов вернёт `success=False` с fallback. Поэтому один
  `except ReviewRequired` не гарантирует перехват всякой неопределённости;
  нужна проверка итогового `SamplingResult`. Это проверено чтением исходника,
  а не выполнением настоящего sampling в среде сборки.
- [Inference-Time Scaling](https://docs.mellea.ai/advanced/inference-time-scaling):
  `RepairTemplateStrategy` добавляет feedback к инструкции;
  `RejectionSamplingStrategy` повторяет исходную генерацию.
- [Экспорты sampling v0.7.0](https://github.com/generative-computing/mellea/blob/v0.7.0/mellea/stdlib/sampling/__init__.py):
  подтверждён импорт `RepairTemplateStrategy` из `mellea.stdlib.sampling`.
- [Ollama integration](https://docs.mellea.ai/integrations/ollama):
  генератор запускается отдельно; ключ Jev не заменяет генератор.

## Наши решения, а не свойства внешних API

Пороги 0.90/0.10, три Noul исхода, исключение `ReviewRequired`, отсутствие
сетевых retries, фильтрация финального результата, отсутствие redirects,
ограничение Choice schema и узкий состав `state` — политика этого адаптера.
Ни Mellea, ни Jev не дают в этом проекте доказательства истинности ответа.
Неопределённость не автоматически переключает SOFAI; вторую проверку
должен явно организовать вызывающий код.
