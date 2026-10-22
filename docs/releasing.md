# Как выпустить v0.2.0 в GitHub

Релиз — проверенный коммит `main`, неизменяемый тег `v0.2.0` и страница GitHub
Release. Коммит и push сами по себе релиз не создают. Подготовка файлов не означает,
что релиз опубликован. Уже опубликованный `v0.1.0` не нужно изменять.

## 1. Проверить релизную ветку

Ветка подготовки: `chore/prepare-v0.2.0`. В неё входят версии, документация,
редактируемая архитектурная схема и запись фактических проверок.

```bash
git branch --show-current
git status --short
git diff --check
git diff
```

Версия продукта `0.2.0` указана в `pyproject.toml`, `uv.lock`,
`frontend/package.json` и `frontend/package-lock.json`. FastAPI берёт версию из
метаданных установленного Python-пакета; после смены версии выполни
`uv sync --locked --dev`. Версия Java-демо независима. `schema_version: 1` у
снимков и экспорта — версия формата данных, её не нужно заменять на `0.2.0`.

Запусти проверки из README **Checks and CI**,
[проверки PostgreSQL](persistence.md#test-databases) и
[браузерные проверки](ui-development.md#browser-end-to-end-checks).
Дополнительно проверь offline evaluation:

```bash
uv run --locked python scripts/evaluate_investigations.py
uv run --locked python scripts/evaluate_investigations.py \
  --dataset evals/metric-boundaries.json --output data/metric-boundary-results.json
```

Live LLM не запускается обычными тестами или CI. Предыдущие реальные прогоны
записаны отдельно: [учёт использования](usage-validation.md) и
[читаемость отчёта](validation/2026-10-21-report-readability.md). Новый платный
запрос для изменения только версий и документации не требуется.

## 2. Проверить собранное приложение

На локальном демонстрационном окружении с выключенной моделью:

```bash
docker compose -f compose.yaml -f compose.persistence.yaml config --quiet
docker compose -f compose.yaml -f compose.persistence.yaml up -d --build --wait --wait-timeout 180
uv run --locked python scripts/check_compose_demo.py
uv run --locked python scripts/check_investigation_metrics.py
uv run --locked python scripts/check_investigation_context.py
uv run --locked python scripts/check_investigation_storage.py
uv run --locked python scripts/check_investigation_storage.py --investigator-url http://127.0.0.1:3000/api
```

В `frontend/` выполни `npm run test:e2e:compose` и `npm run test:e2e:history`.
Проверь историю, страницу сохранённого отчёта после обновления браузера и Usage.
Без вызовов модели Usage показывает отсутствие использования, а не выдуманные
токены. После обычного перезапуска снимок должен остаться доступен. Тестовую БД
для pytest используй отдельно от БД демо.

Не запускай `down --volumes` на окружении с нужной историей: эта команда удаляет
данные. Для остановки достаточно:

```bash
docker compose -f compose.yaml -f compose.persistence.yaml stop
```

## 3. Закоммитить и открыть PR

В Source Control проверь и добавь только файлы этой доработки. Приватный `.env`,
API-ключи, `data/`, кеши, `node_modules/` и результаты тестов в коммит не входят.

```bash
git diff --cached --check
git diff --cached --stat
git commit -m "chore: prepare v0.2.0 release"
git push -u origin HEAD
```

Создай PR с base `main` и заголовком **Prepare v0.2.0 release**. Укажи
возможности, выполненные проверки и ссылку на
[запись проверки](validation/2026-10-22-v0.2.0.md).

Дождись всех обязательных проверок. В workflow **CI** выполняются `checks`,
`storage`, `frontend`, `java-demo` и зависящий от них `docker-demo`.
**Security scan** работает отдельным workflow. **Publish Python coverage badge**
пропускается на PR намеренно и публикует бейдж после Python-проверок push в `main`;
его пропуск на PR не является ошибкой.

## 4. Слить PR и выбрать проверенный коммит

Проверь финальный diff и используй **Squash and merge**. Дождись успешных **CI**
и **Security scan** для нового коммита `main`, затем обнови локальную ветку:

```bash
git switch main
git pull --ff-only origin main
git log -1 --oneline
```

Рабочие изменения перед переключением должны быть сохранены в коммите.
Тег ставится на SHA, который прошёл проверки. Если после проверки в `main`
появился новый коммит, дождись его проверок или выбери проверенный SHA явно.

## 5. Опубликовать GitHub Release

1. Открой **Releases → Draft a new release**.
2. В **Choose a tag** введи `v0.2.0` и выбери создание нового тега.
3. В **Target** выбери проверенный коммит `main` из предыдущего шага.
4. Название: **v0.2.0 — Saved investigations and model usage**.
5. Скопируй [docs/releases/v0.2.0.md](releases/v0.2.0.md) в описание.
6. Проверь ссылки в preview. Ссылки на тег `v0.2.0` заработают после публикации.
   Старое видео остаётся подписанным как демонстрация `v0.1.0`; оно уже доступно
   по ссылке и не должно представляться новой записью.
7. Для проверенной версии `v0.2.0` оставь **Release label → None**. Для отдельного
   тестового кандидата используй `v0.2.0-rc.1` и **Pre-release**.
8. Нажми **Publish release**, когда описание и target проверены.

Не создавай тот же тег заранее в терминале, если создаёшь его через форму.
После публикации проверь страницу релиза, тег, badge Release в README, ссылки
на инструкции и видео. Задержка обновления бейджа возможна из-за кеша.

Публикация тега в этом проекте не запускает отдельную сборку, деплой или
публикацию Docker-образов. GitHub приложит архив исходников. Обнаруженную после
релиза ошибку исправляй обычным PR и новой версией `v0.2.1`; опубликованный тег
`v0.2.0` не передвигай.
