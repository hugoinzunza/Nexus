# NexUX — Rediseño a producto multi-usuario

Blueprint del paso de NexUX (hub personal de Hugo) a **producto multi-usuario**.
Se ejecuta por fases; este documento es la fuente de verdad del diseño.

## 1. Visión

Cada usuario **conecta su exchange (solo-lectura)** y obtiene su **diario de trading
honesto** + el **co-piloto SMC en vivo**. Arranca como **beta cerrada** con traders
conocidos que ayudan a construir (gente con criterio que opina sobre el SMC). Hugo
opera como **CEO/Admin**: todo lo de un usuario + el **laboratorio** (forward-test +
graduador de Claude) + **gestión** (usuarios, invitaciones, salud).

> El split clave: el **Diario** es valor sólido → producto para usuarios. El
> **laboratorio** (estrategia aún sin edge probado) madura en el lado admin. El
> co-piloto SMC sí se expone a los beta (traders) como *contexto de mercado, no
> asesoría* — su feedback crítico es parte del valor de la beta.

## 2. Roles

| Capacidad | Usuario (beta) | Admin (Hugo) |
|---|---|---|
| Diario personal (su Binance, solo-lectura) | ✅ | ✅ |
| Co-piloto SMC en vivo | ✅ | ✅ |
| Laboratorio: forward-test + graduador Claude | — | ✅ |
| Gestión: usuarios, invitaciones, salud del sistema | — | ✅ |

## 3. Mapa de la app (arquitectura de información)

**Sin sesión (público):**
- **Landing** (`nexux.cl`) — propuesta de valor + CTA registrarse/entrar.
- **Auth** — Google OAuth (gateado por allowlist de invitados en la beta).

**Con sesión — usuario:**
- **Onboarding** — "Conecta tu Binance" (si aún no hay exchange conectado).
- **Diario** — PnL neto, win rate, profit factor, por par/sesión/día/hora, curva de
  equity, posiciones abiertas, holdings spot.
- **Co-piloto** — SMC en vivo (zonas POI, estructura, régimen), informativo.

**Con sesión — admin (Hugo):** todo lo anterior +
- **Laboratorio** — forward-test de setups + graduador sombra de Claude (el "diario
  de pruebas" actual) + el lab de backtest.
- **Gestión** — lista de usuarios, invitaciones, salud (colector/VPS, ingestas).

## 4. Flujos clave

### 4.1 Auth + roles
Google OAuth → si el email está en el **allowlist de invitados** → entra (sin
contraseñas que filtrar). Rol en `users` (`user` | `admin`); Hugo = admin. Sesión
por cookie httponly/secure/samesite.

### 4.2 Conectar exchange (la parte sensible — hacerla bien)
1. Usuario pega API key/secret **read-only** de Binance.
2. **Verificar permisos al conectar:** `GET /sapi/v1/account/apiRestrictions` →
   **rechazar** si `enableWithdrawals` o trading están activos. No confiar en que el
   usuario lo configure bien.
3. Validar que la llave funciona (una lectura real).
4. **Cifrar con sobre** (AES-256-GCM; data-key por registro envuelta por la KEK) y
   guardar en `exchange_connections` por usuario. El frontend nunca ve la llave.

### 4.3 Diario por usuario
El **colector (VPS)** itera los usuarios con exchange conectado, **descifra sus
llaves en memoria**, lee Binance y empuja datos **por-usuario** a Railway, que los
guarda en `ingested_data` (user_id) y los sirve. Cada quien ve lo suyo.

## 5. Arquitectura (sobre lo ya construido)

**Hecho (Fase 1 Postgres):** `users`, `ingested_data` (JSONB por user_id+kind),
`push_subscriptions`; capa `core/store.py` conmutable (Postgres con DATABASE_URL,
si no JSON); Alembic; corriendo en Railway.

**Falta:**
- `role` en `users` (user/admin) + capa de **auth** (Google OAuth + sesiones).
- `exchange_connections` (bóveda cifrada) + flujo conectar-exchange.
- **Colección por-usuario** (colector multi-usuario en el VPS).
- UX del producto (app shell user/admin, diario de usuario, landing).

## 6. Plan de fases (orden de construcción)

| Fase | Qué | Desbloquea |
|---|---|---|
| **A** | **Auth + roles** (Google OAuth + allowlist + rol admin/user + gate de sesión) | Todo lo multi-usuario; el split user/admin |
| **B** | **Bóveda + conectar exchange** (cifrado de sobre + verificación read-only) | Que un usuario aporte sus llaves de forma segura |
| **C** | **Colección por-usuario** (colector multi-usuario en el VPS) | Diarios reales por usuario |
| **D** | **UX**: app shell + diario de usuario + co-piloto (rediseño visual) | La experiencia del producto |
| **E** | **Vista admin** (laboratorio + gestión de usuarios/invitaciones/salud) | Operar la beta |
| **F** | **Landing pública + onboarding** pulido | Captar e incorporar beta testers |

## 7. Dirección visual

Mantener y refinar la estética actual: **dark** (violeta `--accent #6c5ce7` / cyan
`--cyan #22d3ee`), glow ambiental, glass. Marca **NexUX** con el "UX" en cyan.
**Mobile-first / PWA**. Navegación que distinga claro **usuario vs admin**.
Onboarding guiado ("conecta tu exchange en 3 pasos").

## 8. Seguridad (no-negociable)

- Llaves **read-only**; verificación de permisos al conectar (rechazo si retira/opera).
- **Cifrado de sobre**; nunca loguear/exponer/commitear llaves.
- **La web pública (Railway) solo guarda ciphertext**; el **descifrado vive en el
  colector (VPS)** → si se compromete la web, no se leen llaves (defensa en profundidad).
- Términos / privacidad / disclaimer "no es asesoría financiera" antes de abrir registro.
