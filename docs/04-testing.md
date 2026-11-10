# Автоматические проверки — лабораторная № 4

**Проект:** «Последний рубеж», версия игры 0.6.0.  
**Объект проверки:** контракт голосования [`POST /api/rooms/{room_id}/vote`](interface-contract.md), требования **FR-5**, сценарий **US-5**.

## 1. Тест-кейсы

Тесты реализованы в [`backend/tests/test_api.py`](../backend/tests/test_api.py) с использованием `FastAPI TestClient`. Для каждого теста поднимается изолированная тестовая SQLite-БД, создаются новая комната и участники: живой сервер, PostgreSQL и внешние сервисы **не требуются**.

| Тест | Подготовка / вход | Проверяемый результат |
|---|---|---|
| `test_contract_vote_skip_updates_only_voters_private_state` | Три активных игрока, ведущий запускает партию и открывает голосование; игрок отправляет `{"target":"skip"}`, после чего меняет голос на `host.player_id`. | HTTP 200 `{"ok":true}`; личный `state.my_vote`; `vote_count=1`, не увеличивается при замене; другой участник не получает чужой выбор или сырые `votes`. |
| `test_contract_vote_before_voting_is_http_400_without_recording` | Два игрока; ведущий запустил партию, но не открыл голосование (фаза `round`); игрок отправляет `{"target":"skip"}`. | HTTP 400 `{"detail":"Голосовать сейчас нельзя"}`; фаза остаётся `round`; `vote_count=0`, `my_vote=null`. |

Оба теста сопоставимы с успешным и ошибочным примерами в лабораторной № 3. Дополнительно уже существующий `test_skip_and_tie_runoff` проверяет пропуск и второй тур голосования.

## 2. Локальная проверка

Требуется Python 3.12 (как в CI). Команды запуска уже приведены в [README → «Тесты и проверки»](../README.md#тесты-и-проверки).

```bash
cd backend
python -m pip install -r requirements-dev.txt
PYTHONPATH=. python -m pytest -q
```

Для запуска только новых тестов: `PYTHONPATH=. python -m pytest -q -k contract_vote`.  
В Windows PowerShell: `$env:PYTHONPATH='.'; python -m pytest -q`.  
Проверить сборку фронтенда: `cd frontend && npm install && npm run build`.

**Локальная проверка корректной версии тестов:** Linux, Python 3.13.5, 10.11.2026: `28 passed` (26 исходных + 2 новых). CI использует Python 3.12. Сборка фронтенда локально в этой проверке не подтверждена.

## 3. GitHub Actions

Workflow: [`.github/workflows/ci.yml`](../.github/workflows/ci.yml).

- Триггеры: `pull_request` с целью `main` при открытии/новом коммите/повторном открытии; также `push`.
- Job `backend`: checkout, Python 3.12, установка `backend/requirements-dev.txt`, **`python -m compileall -q backend/app`** и `PYTHONPATH=. pytest -q`.
- Job `frontend`: checkout, Node.js 22, `npm install`, `npm run build` (TypeScript + Vite).
- В CI тесты локальные; реальный PostgreSQL или внешние API не нужны.

## 4. Доказательство отрицательного и положительного прогона

Согласно заданию, в **первом коммите** ветки `lab-4` в новом тесте намеренно ожидается HTTP **201** вместо реального **200**. Это *временный дефект теста*, а не ошибка API: проверка должна упасть на сравнении `200 != 201`. Во **втором отдельном коммите** ожидание восстанавливается на `200`; после него тесты должны пройти.

**Подтверждённые запуски GitHub Actions для коммитов PR #8:**

- 🔴 **[Failed — run 42851272229](https://github.com/Ferraronp/bunker-online/actions/runs/42851272229)** на коммите `69d9692`. Job `backend`: `1 failed, 27 passed`, причина — `assert 200 == 201` в `test_contract_vote_skip_updates_only_voters_private_state`; job `frontend` прошёл.
- 🟢 **[Passed — run 42851472623](https://github.com/Ferraronp/bunker-online/actions/runs/42851472623)** на отдельном исправляющем коммите `c3d99a6`. Job `backend`: `28 passed`, job `frontend`: успешно (`npm run build`). Компиляция Python прошла.

Оба приведённых прогона вызваны событием `push` в ветке `lab-4` (открытого PR #8); workflow также настроен на `pull_request` в `main`. Ссылки продублированы в описании PR.

## 5. Ревью и завершение

Другой участник команды (либо другой студент при индивидуальной работе) просматривает тесты и CI, оставляет содержательный комментарий. После исправлений и успешного CI PR сливается в `main`, тег `lab-4` ставится на итоговый коммит. До реального ревью, merge и тега работа остаётся на проверке.
