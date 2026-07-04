# Log de resultados de recaptura BTA

Estado: `template_pending_clean_recapture`

Este archivo se llena después de navegar TradingView limpio. No cuenta como evidencia visual hasta que cada item tenga `status=confirmed` y `captured_file`.

## Estados válidos

- `pending`: no revisado todavía.
- `confirmed`: captura visual coincide con los marcadores esperados.
- `no_annotation`: fecha alcanzada, sin anotación útil del profe.
- `blank_projection`: navegación cayó en margen blanco/proyección.
- `not_matching`: lo visible no coincide con la expectativa del candidato.
- `needs_review`: hay captura, pero requiere decisión manual.

## Conteo

| status | count |
| --- | --- |
| needs_review | 1 |
| not_matching | 2 |
| pending | 29 |

## Items

| status | priority | time | dir | tf | target_file | captured_file |
| --- | --- | --- | --- | --- | --- | --- |
| pending | critical | 2024-05-27 15:00 | short | 15m | 2024-05-27_1500_short_15m_bta_recapture.jpg | - |
| not_matching | critical | 2024-06-12 14:15 | short | 1h | 2024-06-12_1415_short_1h_bta_recapture.jpg | attempt_2024-06-12_1415_after_go_check.png |
| pending | critical | 2024-07-03 03:00 | long | 1h | 2024-07-03_0300_long_1h_bta_recapture.jpg | - |
| pending | critical | 2024-08-01 15:00 | long | 15m | 2024-08-01_1500_long_15m_bta_recapture.jpg | - |
| pending | critical | 2024-09-17 15:00 | short | 15m | 2024-09-17_1500_short_15m_bta_recapture.jpg | - |
| pending | critical | 2024-10-02 10:45 | long | 15m | 2024-10-02_1045_long_15m_bta_recapture.jpg | - |
| pending | critical | 2024-11-15 12:00 | short | 1h | 2024-11-15_1200_short_1h_bta_recapture.jpg | - |
| pending | critical | 2024-11-15 12:00 | short | 4h | 2024-11-15_1200_short_4h_bta_recapture.jpg | - |
| pending | critical | 2025-02-02 18:30 | long | 1h | 2025-02-02_1830_long_1h_bta_recapture.jpg | - |
| pending | critical | 2025-02-19 10:00 | short | 1h | 2025-02-19_1000_short_1h_bta_recapture.jpg | - |
| not_matching | critical | 2025-03-03 19:45 | long | 1h | 2025-03-03_1945_long_1h_bta_recapture.jpg | attempt_2025-03-03_1945_after_go_check.png |
| pending | critical | 2025-03-12 14:30 | long | 1h | 2025-03-12_1430_long_1h_bta_recapture.jpg | - |
| pending | critical | 2025-05-15 16:30 | short | 1h | 2025-05-15_1630_short_1h_bta_recapture.jpg | - |
| pending | critical | 2025-05-20 19:15 | short | 15m | 2025-05-20_1915_short_15m_bta_recapture.jpg | - |
| pending | critical | 2025-07-18 08:30 | long | 15m | 2025-07-18_0830_long_15m_bta_recapture.jpg | - |
| needs_review | critical | 2025-12-29 10:45 | long | 1h | 2025-12-29_1045_long_1h_bta_recapture.jpg | 2025-12-29_1045_long_1h_bta_recapture.jpg |
| pending | high | 2026-01-21 17:00 | long | 15m | 2026-01-21_1700_long_15m_bta_recapture.jpg | - |
| pending | high | 2026-02-18 15:30 | short | 1h | 2026-02-18_1530_short_1h_bta_recapture.jpg | - |
| pending | high | 2026-03-19 14:15 | long | 15m | 2026-03-19_1415_long_15m_bta_recapture.jpg | - |
| pending | high | 2026-05-15 13:30 | long | 4h | 2026-05-15_1330_long_4h_bta_recapture.jpg | - |
| pending | medium | 2024-01-03 09:00 | short | 15m | 2024-01-03_0900_short_15m_bta_recapture.jpg | - |
| pending | medium | 2024-02-23 07:30 | long | 15m | 2024-02-23_0730_long_15m_bta_recapture.jpg | - |
| pending | medium | 2024-03-14 19:30 | long | 15m | 2024-03-14_1930_long_15m_bta_recapture.jpg | - |
| pending | medium | 2024-04-26 10:45 | long | 15m | 2024-04-26_1045_long_15m_bta_recapture.jpg | - |
| pending | medium | 2024-12-11 15:00 | short | 15m | 2024-12-11_1500_short_15m_bta_recapture.jpg | - |
| pending | medium | 2025-01-31 20:15 | long | 15m | 2025-01-31_2015_long_15m_bta_recapture.jpg | - |
| pending | medium | 2025-04-30 13:45 | long | 15m | 2025-04-30_1345_long_15m_bta_recapture.jpg | - |
| pending | medium | 2025-06-24 16:45 | short | 15m | 2025-06-24_1645_short_15m_bta_recapture.jpg | - |
| pending | medium | 2025-08-28 18:45 | long | 15m | 2025-08-28_1845_long_15m_bta_recapture.jpg | - |
| pending | medium | 2025-09-12 17:00 | short | 15m | 2025-09-12_1700_short_15m_bta_recapture.jpg | - |
| pending | medium | 2025-10-20 06:30 | short | 1h | 2025-10-20_0630_short_1h_bta_recapture.jpg | - |
| pending | medium | 2025-11-10 09:15 | short | 15m | 2025-11-10_0915_short_15m_bta_recapture.jpg | - |

## Uso

1. Capturar el chart limpio con el nombre `target_file` cuando coincida.
2. Cambiar `status` en el JSON.
3. Rellenar `captured_file`, `observed_markers`, `notes`, `reviewed_by` y `reviewed_at`.
4. Regenerar cobertura y paquete.
