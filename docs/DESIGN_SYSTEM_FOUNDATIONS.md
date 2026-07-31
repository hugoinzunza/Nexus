# NEXUX Command Center — Design System Foundations

- **Estado:** Experimental; Sprint B1
- **Versión:** 0.1
- **Fecha:** 2026-07-30
- **Superficie objetivo:** ARZOPA 1920 × 1080, luminancia relativa limitada

## 1. Alcance

Este documento define los tokens visuales mínimos para validar el primer viewport.
No es una librería de componentes ni una aprobación estética. Los valores pueden
cambiar después de las pruebas físicas de legibilidad, densidad y reconocimiento.

La fuente ejecutable de estos tokens es
`modules/command_center/public/command-center.css`.

## 2. Principios

- El fondo es gris casi negro para conservar separación tonal sin usar negro
  absoluto.
- Las superficies se distinguen principalmente por luminancia y borde, no por
  sombras.
- El color comunica estado; no decora.
- Ningún estado depende solo del color: siempre tiene texto o forma.
- La vista persistente responde primero si existe algo que requiere atención.
- TradingView conserva su propia superficie, pero no define el lenguaje visual
  del resto del Command Center.

## 3. Color

| Token | Valor | Uso |
|---|---:|---|
| `--bg` | `#101316` | Fondo general |
| `--surface-1` | `#171b1f` | Bandas y paneles |
| `--surface-2` | `#1d2227` | Filas y énfasis estructural |
| `--surface-raised` | `#242a30` | Superficie elevada excepcional |
| `--text-1` | `#f4f7f8` | Texto y valores primarios |
| `--text-2` | `#aeb8bf` | Contexto y etiquetas |
| `--text-3` | `#7f8a92` | Metadatos no críticos |
| `--border` | `#323a41` | Separación |
| `--border-strong` | `#46515a` | Foco estructural |
| `--info` | `#59c3d8` | Información activa |
| `--success` | `#49c58b` | Estado estable |
| `--warning` | `#e9b44c` | Degradación o stale |
| `--danger` | `#ef6a6a` | Crítico, expired o desconectado |
| `--unknown` | `#97a1a8` | Estado no determinado |

Los contrastes se verifican automáticamente contra `--bg` y `--surface-1`.
`--text-3` solo puede usarse en metadatos no críticos; si la prueba física falla,
deberá aclararse antes de reducir tipografía o peso.

## 4. Tipografía

Se usa la pila del sistema para evitar carga de fuentes y variaciones durante la
medición.

| Token | Tamaño inicial | Uso |
|---|---:|---|
| `--font-xs` | 12 px | Metadatos prescindibles |
| `--font-sm` | 14 px | Texto operacional |
| `--font-md` | 16 px | Estado y títulos compactos |
| `--font-lg` | 20 px | Identidad y valores secundarios |
| `--font-xl` | 28 px | Métricas destacadas |
| `--font-display` | 44 px | Una lectura principal |

Los números comparables usan variantes tabulares. No se escala tipografía con el
ancho del viewport.

## 5. Espaciado y forma

- Unidad base: 4 px.
- Escala: 4, 8, 12, 16, 24 y 32 px.
- Radios: 4 px para controles y 8 px como máximo para superficies.
- Controles: mínimo inicial de 34 px.
- Sombras: ninguna en B1; la separación actual no las necesita.
- Movimiento: solo transiciones breves de estado y respetando
  `prefers-reduced-motion`.

## 6. Estados de la shell

| Estado | Interpretación visual |
|---|---|
| `loading` | Contexto en reconstrucción; acción bloqueada |
| `ready` | Snapshot y Gateway vigentes |
| `degraded` | Snapshot utilizable sin garantía incremental completa |
| `stale` | Una fuente superó `stale_at` |
| `expired` | El contexto no debe usarse para decidir |
| `disconnected` | No existe contexto utilizable |

La shell deriva `stale` y `expired` desde timestamps del Wire ABI, no desde una
decisión visual local.

## 7. Pendientes de validación física

- Confirmar 12, 14, 16 y 20 px desde la distancia real.
- Confirmar que `--text-3` sea legible con brillo diurno y nocturno.
- Medir el máximo de módulos reconocibles sin búsqueda visual.
- Medir montaje y espacio mínimo útil de TradingView.
- Ejecutar la regla de los dos segundos con estados ready, warning y expired.

Ningún token queda definitivo hasta registrar estas pruebas en
`VALIDATION_LOG.md`.
