# NEXUX Command Center — Design System Foundations

- **Estado:** Base B2 perceptualmente aprobada; Sprint B3 candidato técnico
- **Versión:** 0.2
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
| `--bg` | `#111519` | Fondo general |
| `--surface-1` | `#1d2328` | Bandas y paneles |
| `--surface-2` | `#242b31` | Filas y énfasis estructural |
| `--surface-raised` | `#2b333a` | Superficie elevada excepcional |
| `--text-1` | `#f4f7f8` | Texto y valores primarios |
| `--text-2` | `#c1c9ce` | Contexto y etiquetas |
| `--text-3` | `#929da5` | Metadatos no críticos |
| `--border` | `#46515a` | Separación |
| `--border-strong` | `#5a6670` | Foco estructural |
| `--info` | `#65d2e8` | Información activa |
| `--success` | `#56d99a` | Estado estable |
| `--warning` | `#f2bd50` | Degradación o stale |
| `--danger` | `#ff7272` | Crítico, expired o desconectado |
| `--unknown` | `#aab4bb` | Estado no determinado |

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

VAL-0017 aprobó físicamente los tamaños y la lectura general de B1. B2 aumenta
moderadamente la separación tonal y la intensidad semántica para compensar la
luminancia relativa del Arzopa. VAL-0018 aprobó perceptualmente estos tokens.
B3 puede estudiar mayor saturación de estados, pero no debe reemplazar esta base
sin nueva evidencia física.

## 8. Extensión B3

B3 no cambia los tokens de color. Refuerza el panel operacional con
`--surface-2` y utiliza puntos de 9 px junto con texto explícito. El color no es
la única señal: `Ready`, `Degraded`, `Failed` y `Unknown` siempre permanecen
escritos.

El panel ocupa el mismo track de B2 y distribuye ocho servicios en dos columnas.
Esta densidad queda como candidata hasta la validación perceptual VAL-0019.
