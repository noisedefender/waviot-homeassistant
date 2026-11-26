# Home Assistant интеграция WAVIoT (lk.waviot.ru)

<img src="assets/waviot.png" width="128" alt="Логотип WAVIoT">

Custom-интеграция для [Home Assistant](https://www.home-assistant.io/), которая
читает показания электросчётчика из личного кабинета WAVIoT
([lk.waviot.ru](https://lk.waviot.ru)) — там же, где их показывает ваш дом.

## Что она делает

- Вход в личный кабинет по логину и паролю (e-mail или телефон) — данные
  вводятся в интерфейсе Home Assistant и нигде не хранятся в коде репозитория.
- Автоматически забирает персональный ключ API со страницы
  `https://lk.waviot.ru/api/`, дальше работает по ключу без cookies.
- Опрашивает кабинет и создавает сущности для каждого счётчика на элементе (доме).

## Сущности

Для каждого счётчика (электричество, вода, газ — что привязано к элементу):

| Сущность | Что это | Единица |
| --- | --- | --- |
| `sensor..._total_energy` | суммарное показание счётчика (`electro_ac_p_lsum_tsum`) | kWh |
| `sensor..._tariff_1..4` | показание по тарифу (только существующие каналы) | kWh |
| `sensor..._total_energy_per_day` | расход за последние 24 часа (из баланса кабинета) | kWh |
| `sensor..._last_reading` | время последней передачи показаний | timestamp |
| `sensor..._battery_voltage` | напряжение батарейки модема (выключено по умолчанию) | V |
| `sensor..._modem_temperature` | температура модема (выключено по умолчанию) | °C |
| `sensor..._signal_strength` | уровень радио-сигнала RSSI (выключено по умолчанию) | dBm |

Суммарные показания имеют `state_class = total_increasing`, поэтому из них
обычными automation'ами/`derive` можно считать дневной расход.

## Установка

### Вручную

1. Скопируйте папку `custom_components/waviot` в
   `config/custom_components/waviot` вашего Home Assistant.
2. Перезапустите HA.
3. Настройки → Устройства и службы → Интеграции → Добавить интеграцию → **WAVIoT**.
4. Введите логин и пароль от личного кабинета.

### Через HACS

Добавьте этот репозиторий как пользовательский (custom) репозиторий в HACS
(тип «Integration») и установите «WAVIoT».

## Параметры при добавлении

- **Логин** — e-mail или телефон, которым вы входите в кабинет.
- **Пароль** — пароль от кабинета.
- **Ключ API** — необязательно. Если вставите ключ со страницы
  `https://lk.waviot.ru/api/`, пароль не нужен и интеграция не делает вход.
- **ID элемента** — необязательно. По умолчанию берётся элемент, который
  кабинет показывает на главной странице (`elementId` в `/`). Если у вас
  несколько элементов (дом, дача, квартира), добавьте несколько интеграций с
  разными ID элемента. Список элементов: `https://lk.waviot.ru/api.tree/get_tree/?key=...`.

## Опции

В настройках интеграции можно менять интервал опроса (по умолчанию 15 минут).
Счётчики WAVIoT обычно передают показания раз в час, поэтому чаще опрашивать
смысла нет.

## Двухфакторная авторизация

Если в кабинете включён SMS-код при входе, автоматический вход невозможен:
интеграция сообщит об этом и предложит отключить 2FA или ввести ключ API.

## Пример: суточный расход в Lovelace

```yaml
sensor.waviot_8146244_total_energy          # 46461.016 kWh
sensor.waviot_8146244_total_energy_per_day  # 9.566 kWh за сутки
```

## API, который использует интеграция

```
https://lk.waviot.ru/api.data/get_full_element_info/?id=<element>&key=<key>
https://lk.waviot.ru/api.tree/get_modems/?id=<element>&key=<key>
https://lk.waviot.ru/api.data/get_balance_info/?elementId=<element>&from=<ts>&to=<ts>&key=<key>
```

Документация методов: <https://lk.waviot.ru/api/>

## Иконка интеграции

Начиная с Home Assistant 2026.3 custom-интеграция может хранить свои картинки
сама — для этого рядом с `manifest.json` лежит папка `brand/`:

```
custom_components/waviot/brand/
├── icon.png          256×256, для светлой темы
├── icon@2x.png       512×512
├── dark_icon.png     256×256, белая — для тёмной темы
└── dark_icon@2x.png  512×512
```

Локальные картинки имеют приоритет над изображениями из CDN `brands.home-assistant.io`,
никакой дополнительной настройки не нужно. Иконка квадратная, с прозрачным фоном
и обрезана по краю рисунка — это требования спецификации брендов.
Отдельный `logo.png` не добавлен: рисунок квадратный и совпадает с иконкой, а
при совпадении HA использует `icon.png` как логотип.

Файлы генерируются из вектора `assets/waviot.svg` скриптом
`assets/render-logo.ps1` (Windows PowerShell, GDI+):

```powershell
powershell.exe -ExecutionPolicy Bypass -File assets/render-logo.ps1
```

Требования по версии Home Assistant:

- **2026.3 и новее** — иконка берётся из `brand/` этой интеграции.
- **2026.2 и старее** — HA спрашивает картинку у CDN, поэтому её там нет. Чтобы
  иконка появилась и на старых версиях, отправьте PR в
  [home-assistant/brands](https://github.com/home-assistant/brands) с теми же
  четырьмя файлами в папке `custom_integrations/waviot/` (symlinks там запрещены).
- **Marketplace / HACS** показывает превью иконки из репозитория integration на
  пути `https://brands.home-assistant.io/marketplace/waviot/icon.png`; этот путь
  заполняется только после публикации GitHub release.
- Сущности имеют свои иконки независимо от логотипа: `mdi:flash` для
  электричества, `mdi:water` / `mdi:fire` для воды и газа, `mdi:battery`,
  `mdi:thermometer`, `mdi:signal`.

## Версия и видимость в Marketplace

Начиная с Home Assistant 2026.11 HACS встроен в HA как Marketplace.

**Версия.** Marketplace берёт версию из GitHub release; если релизов нет,
показывает первые 7 символов последнего коммита (например `dcbed01`). Опубликуйте
тег и релиз:

```bash
git tag v0.1.4 && git push origin v0.1.4
```

Затем на GitHub создайте release для этого тега — одного тега недостаточно,
нужен именно релиз. После релиза Marketplace начинает показывать `0.1.4` и
превью иконки из этого репозитория.

**Чтобы интеграцию видели другие пользователи.** Есть два пути:

1. **Custom-репозиторий** — каждый пользователь сам добавляет репозиторий в
   Marketplace (тип «Integration»). Ссылка для перехода прямо к карточке:
   <https://my.home-assistant.io/redirect/hacs_repository/?owner=noisedefender&repository=waviot-homeassistant&category=integration>
   (работает только у тех, кто ссылку открыл, список по умолчанию он не меняет).
2. **Список по умолчанию** — интеграция появляется у всех без добавления
   репозитория. Для этого отправьте PR в [hacs/default](https://github.com/hacs/default),
   в файл [`./integration`](https://github.com/hacs/default/blob/master/integration):
   строка `noisedefender/waviot-homeassistant` в алфавитном порядке, в новой
   ветке от `master` вашего форка.

   Перед PR должны зелёными быть два GitHub Actions (`.github/workflows/hacs.yml`
   и `.github/workflows/hassfest.yml`), должен существовать GitHub release, у
   репозитория должны быть включены issues, описание и topics (например
   `homeassistant`, `waviot`, `energy-meter`, `electricity`), лицензия — MIT,
   а домен `waviot` не должен совпадать с доменом интеграции из core.
   Проверка брендов берёт `custom_components/waviot/brand/icon.png` — он есть.
   От PR до включения обычно проходят месяцы: статус — в
   [backlog](https://github.com/hacs/default/pulls?q=is%3Apr+is%3Aopen+draft%3Afalse+sort%3Acreated-asc).

`country` в `hacs.json` намеренно не задан, чтобы карточка была видна всем
пользователям; если хотите ограничить её только Россией, добавьте
`"country": "RU"`.

## Лицензия

MIT.

