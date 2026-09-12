# Прототип веб-приложения с RPC на основе TCP

Практическая работа №1, вариант 7. Дисциплина «Прикладная разработка
серверных частей веб-приложений на языке Питон».

Выполнил: Коротков, группа ИКБО-70-24.

## Общее описание

Прототип веб-приложения хранит данные только в памяти (на диск ничего
не сохраняется). Схема данных состоит из трёх сущностей: Client,
Prompt и Result. Работа выполняется по этапам:

1. Модель слоя доступа к данным и интерактивный режим (REPL).

Требуется Python 3.10 или новее.

## Структура репозитория

| Путь | Назначение |
|---|---|
| `src/model.py` | модель слоя работы с данными (10 функций) |
| `src/errors.py` | исключения модели |
| `src/repl.py` | интерактивный режим (REPL) |
| `examples/demo.txt` | сценарий демонстрации для REPL |
| `tests/` | тесты |
| `run.sh` | скрипт запуска |

## Схема данных

| Таблица | Столбцы | Внешний ключ |
|---|---|---|
| Client | id: int, time: int, platform: str | — |
| Prompt | id: int, time: int, argument: str, client: int, tags: str, stage: str | client → Client.id |
| Result | id: int, time: int, result: str, stage: str, error: str, prompt: int, cache_hit: int | prompt → Prompt.id |

Связи «один ко многим»: у клиента может быть ноль или несколько
запросов (Prompt), у запроса — ноль или несколько результатов (Result).

Каждая запись хранится в памяти **списком** значений в порядке
столбцов, например `[1, 1791233465, 'linux']` для Client. Таблица —
список таких записей.

Обязательные поля: `id`, `Prompt.client`, `Result.prompt`. Остальные
поля могут иметь значение `None`. Поле `time` — Unix-время в секундах.
Идентификатор `id` назначается автоматически (1, 2, 3, …).

## Функции модели

Все функции находятся в `src/model.py`. Функции создания и изменения
возвращают итоговую запись, функции получения — копии всех записей
таблицы (изменение копий не затрагивает хранилище).

| Функция | Описание |
|---|---|
| `create_client(time=None, platform=None)` | создать Client |
| `get_clients()` | получить все записи Client |
| `update_client(uid, time=KEEP, platform=KEEP)` | изменить Client |
| `create_prompt(time=None, argument=None, client=None, tags=None, stage=None)` | создать Prompt |
| `get_prompts()` | получить все записи Prompt |
| `update_prompt(uid, time=KEEP, argument=KEEP, client=KEEP, tags=KEEP, stage=KEEP)` | изменить Prompt |
| `create_result(time=None, result=None, stage=None, error=None, prompt=None, cache_hit=None)` | создать Result |
| `get_results()` | получить все записи Result |
| `update_result(uid, time=KEEP, result=KEEP, stage=KEEP, error=KEEP, prompt=KEEP, cache_hit=KEEP)` | изменить Result |
| `get_recent_prompts(now=None)` | выборка по формуле варианта |

В функциях изменения значение `KEEP` (по умолчанию) означает «оставить
поле без изменений», поэтому передаются только изменяемые поля:
`update_client(1, platform="macos")`. Значение `None` очищает поле.

### Выборка `get_recent_prompts`

Реализует формулу реляционной алгебры:

```
π[C.platform, P.argument]( (σ[C.time ≥ now − 7 min] C) ⟖[C.id = P.client] P )
```

1. σ — отбираются клиенты, у которых `time ≥ now − 420` секунд.
2. ⟖ — правое внешнее соединение с Prompt по условию
   `C.id = P.client`: сохраняются **все** записи Prompt; если клиент
   записи не попал в выборку, его поля равны `None`.
3. π — проекция на столбцы `platform` и `argument`; повторяющиеся
   строки удаляются, как принято в реляционной алгебре.

Результат — список строк `[platform, argument]`. Параметр `now`
(Unix-время) по умолчанию равен текущему времени.

### Ошибки

| Исключение | Когда возникает |
|---|---|
| `ValidationError` | неверный тип поля или пустое обязательное поле |
| `NotFoundError` | нет записи с указанным `uid` или нет записи, на которую ссылается внешний ключ |

При ошибке хранилище не изменяется.

## Настройки

| Параметр | Значение | Где задан |
|---|---|---|
| Окно выборки `get_recent_prompts` | 7 минут | `RECENT_WINDOW_SECONDS` в `src/model.py` |

## Сборка и запуск

Сборка не требуется. Установка инструментов проверки кода:

```sh
./run.sh install
```

| Команда | Действие |
|---|---|
| `./run.sh repl` | интерактивный режим (REPL) |
| `./run.sh demo` | демонстрация: команды из `examples/demo.txt` |
| `./run.sh lint` | проверка кода flake8 |

Без `run.sh` (например, в Windows): `python -m src.repl` из корня
репозитория.

### Интерактивный режим

Команда вводится как вызов функции модели с аргументами-литералами
Python. Имя `now` в аргументах означает текущее Unix-время, к нему
можно прибавлять и вычитать числа: `create_client(time=now - 60)`.
Служебные команды: `help` (список функций), `now`, `exit`.

## Примеры использования

Вывод `./run.sh demo` (без справки `help`), показаны все функции модели
и обработка ошибок:

```
model> get_clients()
(нет записей)
model> create_client(time=now - 60, platform="linux")
[1, 1791233465, 'linux']
model> create_client(time=now - 3600, platform="windows")
[2, 1791229925, 'windows']
model> create_client(time=now - 120)
[3, 1791233405, None]
model> create_client(time="вчера", platform="linux")
Ошибка ValidationError: поле time: ожидается int, получено str
model> create_client(platform=42)
Ошибка ValidationError: поле platform: ожидается str, получено int
model> get_clients()
[1, 1791233465, 'linux']
[2, 1791229925, 'windows']
[3, 1791233405, None]
model> update_client(3, platform="macos")
[3, 1791233405, 'macos']
model> update_client(1, time=now - 30)
[1, 1791233495, 'linux']
model> update_client(99, platform="android")
Ошибка NotFoundError: Client: запись с id=99 не найдена
model> update_client("1", platform="android")
Ошибка ValidationError: поле id: ожидается int, получено str
model> update_client(1, time=1.5)
Ошибка ValidationError: поле time: ожидается int, получено float
model> get_clients()
[1, 1791233495, 'linux']
[2, 1791229925, 'windows']
[3, 1791233405, 'macos']
model> create_prompt(time=now, argument="hi", client=1, tags="a", stage="new")
[1, 1791233525, 'hi', 1, 'a', 'new']
model> create_prompt(time=now, argument="bye", client=2, stage="new")
[2, 1791233525, 'bye', 2, None, 'new']
model> create_prompt(time=now, argument="ping", client=3)
[3, 1791233525, 'ping', 3, None, None]
model> create_prompt(time=now, argument="hi", client=1, stage="retry")
[4, 1791233525, 'hi', 1, None, 'retry']
model> create_prompt(argument="lost", client=99)
Ошибка NotFoundError: Client: запись с id=99 не найдена
model> create_prompt(argument="no client")
Ошибка ValidationError: поле client: ожидается int, получено NoneType
model> create_prompt(argument=["list"], client=1)
Ошибка ValidationError: поле argument: ожидается str, получено list
model> get_prompts()
[1, 1791233525, 'hi', 1, 'a', 'new']
[2, 1791233525, 'bye', 2, None, 'new']
[3, 1791233525, 'ping', 3, None, None]
[4, 1791233525, 'hi', 1, None, 'retry']
model> update_prompt(2, stage="done", tags="b")
[2, 1791233525, 'bye', 2, 'b', 'done']
model> update_prompt(2, client=99)
Ошибка NotFoundError: Client: запись с id=99 не найдена
model> update_prompt(10, stage="done")
Ошибка NotFoundError: Prompt: запись с id=10 не найдена
model> get_prompts()
[1, 1791233525, 'hi', 1, 'a', 'new']
[2, 1791233525, 'bye', 2, 'b', 'done']
[3, 1791233525, 'ping', 3, None, None]
[4, 1791233525, 'hi', 1, None, 'retry']
model> create_result(time=now, result="ok", prompt=1, cache_hit=0)
[1, 1791233525, 'ok', None, None, 1, 0]
model> create_result(time=now, error="timeout", prompt=2, cache_hit=1)
[2, 1791233525, None, None, 'timeout', 2, 1]
model> create_result(result="orphan", prompt=99)
Ошибка NotFoundError: Prompt: запись с id=99 не найдена
model> create_result(result="bad", prompt=1, cache_hit="yes")
Ошибка ValidationError: поле cache_hit: ожидается int, получено str
model> get_results()
[1, 1791233525, 'ok', None, None, 1, 0]
[2, 1791233525, None, None, 'timeout', 2, 1]
model> update_result(2, error=None, result="pong", stage="done")
[2, 1791233525, 'pong', 'done', None, 2, 1]
model> update_result(1, prompt=99)
Ошибка NotFoundError: Prompt: запись с id=99 не найдена
model> update_result(5, stage="done")
Ошибка NotFoundError: Result: запись с id=5 не найдена
model> get_results()
[1, 1791233525, 'ok', None, None, 1, 0]
[2, 1791233525, 'pong', 'done', None, 2, 1]
model> get_recent_prompts()
['linux', 'hi']
[None, 'bye']
['macos', 'ping']
model> get_recent_prompts(now=now + 600)
[None, 'hi']
[None, 'bye']
[None, 'ping']
model> get_recent_prompts(now="сейчас")
Ошибка ValidationError: поле now: ожидается int, получено str
model> get_recent_prompts
['linux', 'hi']
[None, 'bye']
['macos', 'ping']
model> delete_client(1)
Ошибка ввода: неизвестная команда delete_client, см. help
model> create_client(time=now - 60
Ошибка ввода: '(' was never closed (<unknown>, line 1)
model> exit
```

В последнем вызове `get_recent_prompts()` строка `[None, 'bye']`
получена правым внешним соединением: клиент 2 был активен час назад и
не попал в выборку σ, но его запрос сохранился. Запросы 1 и 4 дают
одинаковую строку `['linux', 'hi']`, проекция оставила одну.
