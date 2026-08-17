# Protocolo de estudio - Bitcoin Traders SMC

**Congelado:** 2026-08-17, antes de analizar las transcripciones completas.

`research_only` | `no_signal` | `no_bot` | `no_production`

## Pregunta

¿Cual es la estrategia SMC que el profesor ensena realmente, expresada como una
secuencia reproducible de contexto, setup, confirmacion, entrada, invalidacion,
gestion y salida?

## Unidad de evidencia

Cada afirmacion del estudio debe incluir:

- sesion;
- timestamp o intervalo;
- contexto visual cuando sea necesario;
- nivel de evidencia;
- contradicciones observadas en otras clases.

## Niveles de evidencia

| Codigo | Significado |
|---|---|
| E0 | Declaracion literal y verificable del profesor |
| E1 | Regla repetida de forma consistente en dos o mas ejemplos |
| E2 | Regla demostrada en una clase practica completa |
| I1 | Interpretacion del analista, no atribuible literalmente al profesor |
| H1 | Hipotesis mecanizable que requiere pre-registro y prueba |
| U0 | Ambiguo, contradictorio o insuficientemente definido |

Una observacion `I1`, `H1` o `U0` nunca se presentara como regla del curso.

## Pasadas obligatorias

1. **Inventario:** verificar titulo, duracion, disponibilidad y hash local.
2. **Transcripcion:** generar texto local con segmentos temporales.
3. **Mapa conceptual:** indexar terminos y reglas candidatas sin sintetizar aun.
4. **Verificacion visual:** revisar el video en los timestamps donde el grafico sea
   necesario para entender la regla.
5. **Consistencia transversal:** buscar ejemplos favorables, desfavorables y
   contradicciones entre sesiones.
6. **Playbook:** redactar la secuencia operativa usando solo evidencia clasificada.
7. **Comparacion:** contrastar con NexUX sin modificar implementacion.
8. **Hipotesis:** convertir solo reglas suficientemente definidas en preguntas
   cuantitativas nuevas.

## Campos del playbook

- sesgo y timeframe rector;
- estructura y fractalidad;
- rango operativo;
- premium/discount, si aplica;
- liquidez interna y externa;
- OB, imbalance/FVG y criterios de calidad;
- iBOS/BOS/CHoCH/CDC y definicion exacta;
- disparador de entrada;
- stop e invalidacion;
- take profit y gestion;
- condiciones de abstencion;
- riesgo y sizing;
- excepciones y discrecionalidad.

## Controles contra sesgo

- No asumir equivalencia entre vocabulario del profesor y el vocabulario NexUX.
- No elegir solo ejemplos ganadores.
- Registrar contradicciones y cambios de criterio.
- No completar reglas ausentes con conocimiento SMC externo.
- No convertir lenguaje probabilistico en causalidad.
- No backtestear antes de fijar una definicion mecanica y un protocolo nuevo.
- No tocar Bot, Testnet, Live, Railway, VPS ni produccion.

## Criterio de completitud

El estudio puede declararse completo solo si:

1. las 11 sesiones tienen transcripcion o incidencia documentada;
2. cada regla del playbook tiene fuente temporal;
3. las ambiguedades permanecen visibles;
4. existe una matriz completa frente a NexUX;
5. cualquier propuesta cuantitativa aparece como hipotesis, no como hallazgo;
6. un verificador puede reconstruir el inventario mediante hashes.
