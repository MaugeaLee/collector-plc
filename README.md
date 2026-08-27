# collector-plc

Edge PLC 수집기. `devices[]`마다 워커 스레드로 PLC를 주기 스캔하고 ZeroMQ PUB으로 게이트웨이에 전달한다.

---

## 주소 문자열 파싱

스캔·쓰기에 쓰는 주소는 `client/addr.py`의 `parse_plc_addr()`으로 분해한다.

### 형식

```text
{디바이스}{번호}[.{비트}]
```

| 예 | 디바이스 | 번호 | 비트 |
|----|----------|------|------|
| `D100` | D | 100 | (워드 전체) |
| `D100.5` | D | 100 | 5 |
| `D800.A` | D | 800 | 10 (16진 A) |
| `R3000` | R | 3000 | (워드 전체) |
| `ZR10` | ZR | 10 | (MC 전용) |

### 워드.비트 (소수점) 규칙 — 미쓰비시 GX Works 호환

16비트 워드 안의 비트를 가리킬 때 점(`.`) 뒤에 인덱스를 붙인다.

| 표기 | 비트 인덱스 |
|------|-------------|
| `.0` ~ `.9` | 0 ~ 9 (10진) |
| `.A` ~ `.F` | 10 ~ 15 (16진, 대소문자 무관) |

동작:

1. **MC (`mode: mc`)** — `McClient.read_device()`가 워드를 읽은 뒤 해당 비트만 0/1로 반환한다.
2. **Modbus (`mode: tcp` / `rtu`)** — D/R 워드를 읽고 동일하게 비트를 추출한다.

비트 인덱스는 항상 **0–15**이다. 범위 밖이면 `E-4001(UNSUPPORTED_ADDR)`.

### 프로토콜별 지원 디바이스

| mode | 지원 | 비고 |
|------|------|------|
| `mc` | D, W, R, ZR, SD, SW, Z (워드), M, X, Y, B, L, F, SM (비트) | pymcprotocol에 문자열 그대로 전달 |
| `tcp` / `rtu` | **D**, **R** (워드·워드.비트) | 아래 Modbus 매핑 필요 |

---

## Modbus (LS XG 등) — D와 R 분리 매핑

Modbus TCP/RTU는 PLC **내부 디바이스 이름**을 Modbus가 모른다.  
collector는 주소 **접두사(D vs R)** 로 분기하고, `plc_setting.json`의 origin과 XG5000 Modbus Settings를 **1:1로 맞춘다**.

### 변환 알고리즘 (`client/modbus_map.py`)

```text
D{n}  →  FC03/04 (d_register_type),  index = n - modbus_d_register_start
R{n}  →  FC03/04 (r_register_type),  index = n - modbus_r_register_start
```

- **D는 D로, R은 R로만** 변환한다. `D3000`과 `R3000`은 서로 다른 origin·함수 영역을 쓴다.
- `index`는 pymodbus 기준 **0-based** (Modbus 40001 = index 0).
- `modbus_r_register_start`이 `null`이면 R 주소는 `E-4001` (의도적 — 매핑 미설정).

### 설정 필드 (`tcp` / `rtu` 디바이스)

| 필드 | 기본값 | 설명 |
|------|--------|------|
| `modbus_d_register_start` | `0` | 이 D 번호 = Modbus index 0 |
| `modbus_d_register_type` | `"holding"` | D 영역 FC03(`holding`) 또는 FC04(`input`) |
| `modbus_r_register_start` | `null` | R 미사용. 설정 시 R 영역 활성 |
| `modbus_r_register_type` | `"input"` | R 영역 FC (보통 Word Read → `input`) |

### XG5000 — D와 R **동시에** Modbus로 노출하는 설정

LS XG Modbus 서버는 워드가 **두 갈래**다. D(`%MW`)와 R(`%R`)은 PLC 내부 메모리 종류가 달라 **Word Write 한 칸에 같이 넣을 수 없다.**  
→ **D는 Word Write, R은 Word Read** 로 나눠 Modbus에 올린다.

```text
  XG5000 Modbus Server
  ┌─────────────────────┐    ┌─────────────────────┐
  │ Word Write Area     │    │ Word Read Area      │
  │ 시작 %MW{d_min}     │    │ 시작 %R{r_min}      │
  └──────────┬──────────┘    └──────────┬──────────┘
             ▼                          ▼
      FC03 Holding (4xxxx)      FC04 Input (3xxxx)
      index 0 = D{d_min}         index 0 = R{r_min}
```

**겹치지 않는 이유:** 4xxxx(Holding)와 3xxxx(Input)은 Modbus **주소 공간이 다르다.**  
둘 다 index 0부터여도 `D1600`과 `R3000`이 서로 덮어쓰지 않는다.

#### XG5000에 넣을 값 (예: D1600~, R3000~ 스캔)

| XG5000 항목 | 입력 | 블록 크기 |
|-------------|------|-----------|
| **Word Write Area Address** | `%MW1600` | (스캔 D 최대 − 1600 + 1) 이상 |
| **Word Read Area Address** | `%R3000` | (스캔 R 최대 − 3000 + 1) 이상 |

시작 주소 = **스캔 번지 중 가장 작은 D/R 번호.** `%MW1600` ↔ `D1600` (번호 동일).

#### collector `plc_setting.json` (XG 숫자와 1:1)

```json
"modbus_d_register_start": 1600,
"modbus_d_register_type": "holding",
"modbus_r_register_start": 3000,
"modbus_r_register_type": "input",
"scan_addresses": ["D1600", "D1650", "R3000", "R3008"]
```

| scan | 계산 | Modbus |
|------|------|--------|
| `D1600` | 1600 − 1600 = 0 | FC03 → 40001 |
| `D1650` | 50 | FC03 → 40051 |
| `R3000` | 3000 − 3000 = 0 | FC04 → 30001 |
| `R3008` | 8 | FC04 → 30009 |

`D` 접두사 → FC03만, `R` 접두사 → FC04만. **D가 R 영역으로 섞이지 않는다.**

#### R만 스캔할 때 (`plc-ls-rtu-1`)

D가 없으면 Word Write Area는 XG에서 최소로 두고, collector는 R만 설정:

```json
"modbus_r_register_start": 3000,
"modbus_r_register_type": "input",
"scan_addresses": ["R3000", "R3008", "R3010"]
```

#### FC03(Holding)만 써야 할 때

LS Modbus 서버는 Word Write **블록 1개**만 Holding에 매핑한다. **D와 R을 동시에 FC03 하나에 넣는 설정은 불가**에 가깝다.

- R도 FC03으로 읽어야 하면: ladder로 `%R` → `%MW` 복사 후 D(MW)만 Modbus 노출  
- 또는 Word Write를 `%R3000`으로만 열어 R만 Holding (이 경우 D는 Modbus 불가)

### 설정 예 (`plc_setting.example.json` RTU)

```json
{
  "modbus_d_register_start": 1600,
  "modbus_d_register_type": "holding",
  "modbus_r_register_start": 3000,
  "modbus_r_register_type": "input",
  "scan_addresses": ["D1600", "R3000", "D1600.0", "R3000.A"]
}
```

---

## MC (미쓰비시) — 대형 D 번지 (예: D510300, D101208)

데이터시트에 `D510300`, `D101208`처럼 **Q CPU 일반 D 범위(약 D0–D12287)를 넘는 번호**가 적혀 있고, PLC에 직접 접속해 확인할 수 없을 때 아래를 순서대로 검토한다.

### 1. 데이터시트 표기가 “순수 D 디바이스”가 아닐 수 있음

- HMI/SCADA **태그 ID**, **주소 코드**, **간접指定**가 `D` 접두사 없이 붙었을 수 있다.
- 다른 벤더 표기를 미쓰비시 `D`로 옮겨 적었을 수 있다.
- **조치**: 데이터시트 작성처에 “MC Protocol 디바이스 코드 + 번호” 확인 요청.

### 2. 다른 디바이스 코드일 가능성

| MC 코드 | 용도 |
|---------|------|
| `D` | 데이터 레지스터 |
| `R` / `ZR` | 파일·링크 레지스터 |
| `W` | 링크 레지스터 (워드) |
| `SD` | 특수 레지스터 |

510300 같은 큰 숫자는 **파일 레지스터(R/ZR)** 이거나 **모듈/버퍼** 주소일 수 있다.  
**조치**: `R510300`, `ZR…` 등으로 MC 읽기 시도(현장 접속 가능해지면).

### 3. PLC 응답 `0x4031` (E-2203)의 의미

collector는 MC `0x4031`을 `E-2203(ADDR_OUT_OF_RANGE)`로 처리한다.  
**프로토콜·파싱 오류가 아니라 PLC가 “그 D 번호는 없다”고 답한 것**이다.

현재 동작:

- 해당 번지만 `value: null`, `error: "E-2203"` — **스캔 전체는 계속**된다.
- `D800.x`, `D000901`처럼 유효한 번지는 정상 수집된다.

### 4. PLC 확인 없이 할 수 있는 것

| 방법 | 설명 |
|------|------|
| **soft-fail 유지** | 잘못된 번지는 E-2203으로 남기고, 유효 번지만 게이트웨이에 전달 (현재 동작) |
| **scan_addresses 분리** | 확실한 번지(`D800.*`, `D000901` 등)만 먼저 운영, 510xxx는 별도 디바이스/플래그로 보류 |
| **plctype 확인** | `plc_setting.json`의 `plctype`(Q/L/iQ-R 등)이 실제 CPU와 일치하는지 |
| **접속 가능해지면 spot check** | GX Works 또는 MC Protocol로 `D510300` 1워드 batch read → 0x4031이면 번지 자체 무효 |

### 5. 접속 가능해질 때 확인 체크리스트

1. CPU 모듈 사양상 D 최대点数
2. 데이터시트 “D510300”이 **디바이스+番号**인지 **タグ名**인지
3. `batchread_wordunits(headdevice="D510300")` 단독 테스트
4. 실패 시 `R` / `ZR` / `W` 동일 번호 시도
5. GOT/HMI 프로젝트에서 동 주소의 **実デバイス** 확인

---

## 관련 소스

| 파일 | 역할 |
|------|------|
| `client/addr.py` | 주소 파싱, 워드.비트(0–9, A–F) |
| `client/modbus_map.py` | Modbus D/R → index 변환 |
| `client/mc_client.py` | MC Protocol 디바이스 읽기/쓰기 |
| `daemon.py` | `read_addr` / `write_addr` — MC vs Modbus 분기 |
| `model/client_model.py` | `ModbusMapSettings`, 디바이스 스키마 |

---

## 실행

```bash
cp plc_setting.example.json plc_setting.json
# .env 설정 후
python main.py
```

자세한 프로젝트 레이아웃·ZeroMQ 토픽은 `.cursor/rules/project-conventions.mdc`, `zeromq-conventions.mdc` 참고.
