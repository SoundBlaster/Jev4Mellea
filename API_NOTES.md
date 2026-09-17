# Проверенные внешние контракты

Дата сверки: **2026-09-17**. Это ссылки на первичные источники, а не запись
удачного live-вызова. Документация сервиса и alias модели могут измениться.

## TypeSafe

[HTTP API reference](https://docs.typesafe.ai/api) описывает:

```text
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <API_KEY>
```

Нужны `model`, `state` и именованный словарь `questions`. Адаптер задаёт
один вопрос с id `requirement`, типом `noul` и инструкцией проверки.
Из ответа читаются `answers.requirement.type`, `answers.requirement.noul`
и `model`. Дополнительные поля не требуют изменения адаптера.
`usage` не используется для решения о принятии, расчёта цены здесь нет.

[Noul](https://docs.typesafe.ai/primitives/noul) возвращает P(yes) от 0 до 1;
это не булево значение и не отдельный confidence. Значение около 0
означает уверенное «нет», а не низкую уверенность в результате «да».

[Quick start](https://docs.typesafe.ai/introduction/quickstart) подтверждает
переменную `TYPESAFE_API_KEY` и alias `jev-latest`.
[Ответы SDK](https://docs.typesafe.ai/sdk/python/api/types/responses) описывают
заголовок `x-typesafe-request-id`, который клиент переносит в метаданные.

[Официальный Python SDK](https://docs.typesafe.ai/sdk/python/api/clients/sync/client)
действительно имеет `TypeSafeClient.system_one(...)`; `jev.decide(...)`
в предыдущем обсуждении был псевдокодом. Этот маленький пакет использует
HTTP напрямую и не зависит от версии SDK.

## Mellea

Цель: `mellea==0.7.0`, Python >=3.11.

- [Write Custom Verifiers](https://docs.mellea.ai/how-to/write-custom-verifiers):
  `Requirement(description, validation_fn=...)` и `ValidationResult`.
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

Пороги 0.90/0.10, три исхода, исключение `ReviewRequired`, отсутствие
сетевых retries, фильтрация финального результата, отсутствие redirects
и узкий состав `state` — политика этого адаптера.
Ни Mellea, ни Jev не дают в этом проекте доказательства истинности ответа.
Неопределённость не автоматически переключает SOFAI; вторую проверку
должен явно организовать вызывающий код.
