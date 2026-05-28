# DESIGN.md — Sistema de diseño Auyan

> Fuente única de verdad del sistema de diseño visual.
> Versión: 1.2 (Bloque 1, Sub-PRs 1.1/1.2 — Mercury light dashboard shell)
> Última actualización: 2026-05-28

---

## Cómo usar este documento

Toda decisión visual del producto pasa por acá. Si vas a tocar un componente, una página, o dudás entre dos opciones, **lee esto primero**. Si lo que vas a hacer no encaja con lo escrito, paramos, lo discutimos, y se actualiza el documento ANTES de tocar código.

Convive con:
- `docs/auyan-master-context.md` — fuente de verdad del negocio (sección 12 define las decisiones de UX).
- `docs/architecture-web.md` — arquitectura técnica del frontend.
- `CLAUDE.md` (raíz) — reglas operativas del proyecto.

---

## Aplicabilidad — qué cubre este documento

El documento se divide en dos capas con alcance distinto:

| Capa | Aplica a | Qué define |
|---|---|---|
| **Parte I — Brand foundation** (§§1-8) | `apps/web` **y** `apps/landing` | Principios, color, tipografía, escalas de espaciado, esquinas, iconos, motion (timing/easing). **Las dos apps respetan estos tokens y no los redefinen.** |
| **Parte II — Patrones de dashboard** (§§9-14) | **Solo `apps/web`** | Densidad por contexto, primitives shadcn, patrones de tabla/formulario/card, accesibilidad, refactor checklist. |
| **Parte III — Landing** (§15) | **Solo `apps/landing`** | Reglas para Aceternity UI: qué hereda de la brand foundation, qué decide la landing por su cuenta. |

**`apps/landing`** usa **Aceternity UI** + Framer Motion (decisión #22 del grill-me). Trae módulos pre-hechos (hero animations, bento grids, scroll triggers, marquee de logos, etc.). No reescribimos esos componentes; lo único que aplicamos es la brand foundation — los tokens de color, font y escalas se inyectan como CSS variables y Aceternity los consume. Patrones de marketing (CTAs hero, pricing tables, FAQs) son responsabilidad de Aceternity, NO de este documento.

**`apps/web`** usa **shadcn/ui** + Tailwind. Componentes utilitarios densos para dashboards. Aquí mandan las §§9-14 con todo: density por contexto super_admin vs cliente, primitives, patrones de tabla/form/card.

---

# Parte I — Brand foundation (aplica a `apps/web` y `apps/landing`)

## 1. Principios

Cinco reglas que ganan en cualquier discusión de diseño.

1. **Claridad sobre densidad sobre decoración.** Si dudás entre meter más data o más espacio, gana lo que ayuda a comprender. Decoración cero.
2. **Sistema sobre artesanía.** Antes de inventar un componente, revisás si ya existe. Antes de inventar un color, revisás si hay token. No hay "este caso es especial".
3. **Confianza tipográfica.** El producto se lee mucho. Tipografía afinada (escala, peso, tracking) hace más por la marca que cualquier ornamento.
4. **Motion que aporta, no que adorna.** Una transición existe para indicar continuidad o causalidad. Si quitarla no se nota, sobra.
5. **Tonos de Auyan, no de la app de moda.** Sierra/Decagon son referencia, no clon. Hay un guiño venezolano en el color (azul cobalto del Salto Ángel) y un castellano cuidado en la copy (sin "configurar", sin "asegúrate", sin "vamos!").

---

## 2. Norte estético (brand-wide)

**"Sierra/Decagon AI-native, light por defecto, con un acento cobalto".**

| Atributo | Decisión |
|---|---|
| Modo por defecto | Dashboard operativo usa `data-theme="mercury"`: shell claro inspirado en Mercury, con cards blancas, sidebar off-white, bordes finos y acento cobalto Auyan. Landing y superficies públicas mantienen light salvo decisión explícita. |
| Paleta | Neutrales cálidos + un solo acento cobalto. Cero gradientes, cero degradés en `apps/web`. (`apps/landing` puede usar gradientes sutiles si Aceternity los trae como parte de un módulo — siempre derivados del cobalto.) |
| Tipografía | Geist Sans (UI + display) + Geist Mono (IDs, JSON, code). |
| Esquinas | Suaves (`6px` botones, `8px` cards, `12px` paneles grandes). Cero esquinas agudas. |
| Sombras | Mínimas en dashboard. Landing puede usar shadows de Aceternity siempre que no rompan el lenguaje (nada neón, nada multicolor). |
| Motion | 150-200ms en dashboard. Landing tiene libertad con Aceternity para hero animations, scroll triggers, etc. — siempre con la misma curva de easing. |
| Iconos | Lucide en `apps/web` (ya en stack). Landing puede traer iconos propios del módulo Aceternity sin reemplazarlos. |

---

## 3. Color

### 3.1 Acento — Cobalto Salto Ángel

Un solo color de acento. Se usa en CTAs primarios, focus states, links activos, badges informacionales, datos clave en charts.

```
cobalt-50   #EFF4FF
cobalt-100  #DBE5FF
cobalt-200  #BFCEFF
cobalt-300  #93AEFF
cobalt-400  #5F84FF
cobalt-500  #2563EB   ← primary
cobalt-600  #1D4ED8
cobalt-700  #1E40AF   ← hover / pressed
cobalt-800  #1E3A8A
cobalt-900  #172554
```

### 3.2 Neutrales (cálidos)

Base de TODO lo que no es acento. Usamos cálidos (no fríos puros) para que el cobalto resalte sin enfriar la interfaz.

```
neutral-0    #FFFFFF
neutral-50   #FAFAF9    ← background app
neutral-100  #F5F5F4    ← background panel sutil
neutral-200  #E7E5E4    ← border default
neutral-300  #D6D3D1    ← border énfasis
neutral-400  #A8A29E    ← text muted secondary
neutral-500  #78716C    ← text muted
neutral-600  #57534E    ← text body alt
neutral-700  #44403C    ← text body
neutral-800  #292524    ← text strong
neutral-900  #1C1917    ← text headings
neutral-1000 #0C0A09    ← absoluto (raras veces)
```

Estos son los tonos `stone` de Tailwind v4 — neutrales cálidos. Se eligieron sobre `slate` (más fríos/azulados) porque dejan respirar al cobalto.

### 3.3 Semánticos

Mínimos. Solo donde el significado lo exige.

```
success-50  #ECFDF5   success-500 #10B981   success-700 #047857
warning-50  #FFFBEB   warning-500 #F59E0B   warning-700 #B45309
danger-50   #FEF2F2   danger-500  #EF4444   danger-700  #B91C1C
info-50     #EFF4FF   info-500    #2563EB   info-700    #1E40AF   ← mismo que cobalto
```

**Regla:** un color semántico SOLO se usa cuando comunica estado real (success = operación OK, warning = aviso accionable, danger = error / destructivo). NO se usa para decorar.

### 3.4 Tokens semánticos (esto es lo que importa en CSS)

El código nunca consume los colores raw arriba — consume estos tokens semánticos. Si decidimos cambiar la paleta mañana, todo se mueve cambiando estos tokens.

```css
/* Surfaces */
--background:           neutral-50   /* fondo de la app */
--surface:              neutral-0    /* cards, panels */
--surface-muted:        neutral-100  /* secciones secundarias */
--surface-elevated:     neutral-0    /* modales, dropdowns */

/* Bordes */
--border:               neutral-200  /* default */
--border-strong:        neutral-300  /* hover, énfasis */
--border-subtle:        neutral-100  /* dividers internos */

/* Texto */
--foreground:           neutral-900  /* headings */
--foreground-body:      neutral-700  /* body */
--foreground-muted:     neutral-500  /* secundario */
--foreground-subtle:    neutral-400  /* terciario, placeholders */
--foreground-on-accent: neutral-0    /* texto sobre cobalto */

/* Acento */
--accent:               cobalt-500
--accent-hover:         cobalt-700
--accent-subtle:        cobalt-50
--accent-foreground:    cobalt-700   /* texto cobalto sobre subtle */

/* Estado */
--success:              success-500
--success-subtle:       success-50
--success-foreground:   success-700

--warning:              warning-500
--warning-subtle:       warning-50
--warning-foreground:   warning-700

--danger:               danger-500
--danger-subtle:        danger-50
--danger-foreground:    danger-700

/* Focus ring */
--ring:                 cobalt-500   /* +outline 2px offset 2px */
```

**Anti-patrón explícito:** nunca uses `text-green-700` o `bg-red-50` directamente en JSX. Si necesitás un verde, va por token semántico (`text-success` o `bg-success-subtle`).

---

## 4. Tipografía

### 4.1 Familia

```
--font-sans: 'Geist', 'Geist Fallback', system-ui, -apple-system, sans-serif
--font-mono: 'Geist Mono', 'ui-monospace', monospace
```

**Por qué Geist:** alternativa libre más cercana a GT America (Sierra) y FK Grotesk Neue (Decagon). Diseñada por Vercel específicamente para producto tech. Variant Mono incluida para IDs, JSON, code snippets.

Se carga vía `next/font/google` para evitar FOUT.

### 4.2 Escala (rem, asumiendo `html { font-size: 16px }`)

| Token | Tamaño | Line-height | Tracking | Uso |
|---|---|---|---|---|
| `text-2xs`  | 11px | 1.4 | +0.02em | Microcopy, timestamps muy compactos |
| `text-xs`   | 12px | 1.4 | +0.01em | Captions, labels en formularios, badges |
| `text-sm`   | 13px | 1.5 | 0 | Body en super_admin (compact), tablas |
| `text-base` | 14px | 1.5 | 0 | Body default; body cliente (relaxed) sube a 15px |
| `text-md`   | 15px | 1.55 | 0 | Body cliente (relaxed) |
| `text-lg`   | 17px | 1.45 | -0.005em | Subtitulares sección |
| `text-xl`   | 20px | 1.35 | -0.01em | Títulos de página secundarios |
| `text-2xl`  | 24px | 1.3  | -0.015em | Títulos de página principales |
| `text-3xl`  | 30px | 1.2  | -0.02em | Métricas grandes, hero numbers |
| `text-4xl`  | 38px | 1.1  | -0.025em | Display, vacíos premium |

### 4.3 Pesos

Geist soporta 100-900. Usamos cuatro pesos.

| Peso | Numérico | Uso |
|---|---|---|
| Regular | 400 | Body, párrafos, descripciones |
| Medium  | 500 | Labels, badges, tabs activos, énfasis sutil |
| Semibold | 600 | Headings h2/h3, números de KPI, buttons |
| Bold | 700 | h1, énfasis máximo (raro) |

**Anti-patrón:** evitar pesos 800/900 (excesivos para producto), 300 (demasiado fino, problemas con acentos en español).

### 4.4 Headings — recomendaciones de uso

| Nivel | Tamaño | Peso | Color |
|---|---|---|---|
| h1 página | text-2xl | 600 | foreground |
| h2 sección | text-xl | 600 | foreground |
| h3 panel | text-lg | 600 | foreground |
| h4 subpanel | text-base | 600 | foreground |
| eyebrow | text-xs uppercase tracking-wider | 500 | foreground-muted |

---

## 5. Espaciado y layout

### 5.1 Escala (base 4px)

```
space-0   0
space-px  1px
space-0.5 2px
space-1   4px
space-1.5 6px
space-2   8px
space-3   12px
space-4   16px
space-5   20px
space-6   24px
space-8   32px
space-10  40px
space-12  48px
space-16  64px
space-20  80px
space-24  96px
```

### 5.2 Densidades (solo `apps/web`)

Dos modos. Se aplican al wrapper raíz de cada sección (cliente vs interno). La landing NO los usa — es uniformemente generosa.

| Token | Compact (super_admin) | Relaxed (cliente) |
|---|---|---|
| `--density-row-y` | 8px (`space-2`) | 12px (`space-3`) |
| `--density-row-x` | 12px (`space-3`) | 16px (`space-4`) |
| `--density-card-p` | 16px (`space-4`) | 24px (`space-6`) |
| `--density-section-gap` | 16px (`space-4`) | 32px (`space-8`) |
| `--density-text-body` | 13px (`text-sm`) | 15px (`text-md`) |

### 5.3 Containers y grids (solo `apps/web`)

- **Max width app**: `1440px` (super_admin tiende a usarlo todo, cliente queda contenido).
- **Sidebar**: 200px fijo en super_admin y cliente, siguiendo el shell Mercury light.
- **Content padding**: `space-6` (cliente) / `space-4` (super_admin).
- **Grid base**: 12 columnas implícitas vía Tailwind, gap `space-4`.

La landing decide sus propios containers y grids dentro de cada módulo de Aceternity.

---

## 6. Esquinas, bordes y sombras

### 6.1 Border radius

```
--radius-xs:  4px    /* badges, chips pequeños */
--radius-sm:  6px    /* buttons, inputs */
--radius-md:  8px    /* cards, panels */
--radius-lg:  12px   /* paneles grandes, modales */
--radius-xl:  16px   /* hero panels (raro) */
--radius-full: 9999px /* avatars, pills */
```

### 6.2 Bordes

- **Border default**: `1px solid var(--border)`.
- **Border énfasis (hover)**: `1px solid var(--border-strong)`.
- **Border focus**: usar `outline`, no `border` (no shifts de layout). `outline: 2px solid var(--ring); outline-offset: 2px`.

### 6.3 Sombras

Mínimas en dashboard, pero las cards principales del shell Mercury light usan la sombra exacta medida en el demo para ganar profundidad sin verse pesadas:

```
card-shadow      ← cards:    0 0 2px 0 rgb(175 178 206 / 0.56), 0 1px 4px 0 rgb(4 4 52 / 0.10)
shadow-sm        ← popovers: 0 1px 2px 0 rgb(0 0 0 / 0.04), 0 1px 3px 0 rgb(0 0 0 / 0.06)
shadow-md        ← modales:  0 4px 12px -2px rgb(0 0 0 / 0.08), 0 2px 6px -1px rgb(0 0 0 / 0.06)
```

**Dashboard**: cero `shadow-xl` o sombras coloridas. Las cards no llevan border visible; la sombra `0 0 2px` hace de contorno fino.

**Landing**: puede usar sombras de Aceternity que vienen como parte de un módulo (spotlight, glow effects sutiles) siempre que respeten la paleta — nada multicolor, nada neón.

---

## 7. Iconografía

- **Librería única**: `lucide-react` (ya en stack).
- **Stroke width**: 1.5 (default del set).
- **Tamaños**: 14, 16, 20, 24. Nada en medio.

| Tamaño | Uso |
|---|---|
| 14 | Inline en texto pequeño (text-xs/sm) |
| 16 | Default — buttons, list items, menús |
| 20 | Énfasis — botones primarios grandes, headings |
| 24 | Empty states, ilustraciones simples |

**Anti-patrón:** mezclar Heroicons o Phosphor con Lucide. Si Lucide no tiene el icono, primero buscamos sinónimo; si no hay, lo discutimos antes de instalar otra librería.

---

## 8. Motion

### 8.1 Tokens (brand-wide)

Timing y easing son compartidos. Lo que cambia entre dashboard y landing son las reglas de USO.

```
--motion-fast:    100ms  /* hover de controles, focus */
--motion-base:    150ms  /* transición default */
--motion-medium:  200ms  /* aparición de paneles, dropdowns */
--motion-slow:    300ms  /* modales, dialogs */
--motion-hero:    600ms  /* landing only: entradas de hero, scroll triggers */
```

```
--ease-out:    cubic-bezier(0.2, 0.8, 0.2, 1)    /* entradas */
--ease-in:     cubic-bezier(0.4, 0, 1, 1)        /* salidas */
--ease-in-out: cubic-bezier(0.4, 0, 0.2, 1)      /* transiciones medidas */
```

### 8.2 Reglas en `apps/web` (dashboard)

- **Hover**: `--motion-fast ease-out` sobre color/background. NO sobre transform/scale.
- **Aparición**: opacity de 0→1 con `--motion-medium ease-out`. NO entradas con translate de más de 8px.
- **Cambios de altura**: evitarlos. Si son inevitables, transition con `--motion-medium ease-in-out`.
- **Loading**: usar `Skeleton` (animación pulse muy sutil, no shimmer).

### 8.3 Reglas en `apps/landing` (marketing)

- Libertad para usar Aceternity (hero animations, scroll-triggered reveals, marquees, bento entrances).
- Las animaciones de hero o scroll usan `--motion-hero` con `--ease-out`. Easing y tokens los hereda Aceternity, no se reescriben.
- Nada de bouncing exagerado, nada de spring overshoots agresivos: Aceternity ofrece defaults agresivos en algunos módulos; los suavizamos.

### 8.4 Universal

- **Respetar `prefers-reduced-motion`**: todas las transiciones se desactivan globalmente cuando el usuario lo tiene activado. Esto aplica a las dos apps sin excepción.

---

---

# Parte II — Patrones de dashboard (solo `apps/web`)

> A partir de acá el documento aplica únicamente a `apps/web`. Para landing, ver §15.

## 9. Densidad por contexto

Reforzando lo de §5.2:

| Contexto | Densidad | Body | Notas |
|---|---|---|---|
| `/dashboard/*` (super_admin) | `compact` | text-sm (13px) | Tablas densas, muchas filas, power tools (Linear-style) |
| `/clients/*` (tenant cliente) | `relaxed` | text-md (15px) | Lectura cómoda, sensación premium (Sierra-style) |
| `/(auth)/login` y similares | `relaxed` | text-base (14px) | Neutro |

El wrapper raíz de cada layout setea la densidad vía `data-density="compact|relaxed"`. Los componentes leen las CSS vars `--density-*`.

## 9.1 Shell operativo Mercury light

`apps/web` usa un shell claro para las áreas autenticadas, siguiendo el demo público de Mercury (`demo.mercury.com`) sin abandonar los tokens Auyan:

- Sidebar fija de 200px, fondo off-white, navegación densa, iconos Lucide de 14px y estado activo gris sutil.
- Topbar de 56px en flujo normal, no fija; desaparece al hacer scroll como en Mercury.
- Sin avatar/cuenta del lado derecho en cliente: Auyan no tiene selector de cuenta cliente en esta etapa.
- Canvas central `max-w-6xl`, fondo blanco, cards blancas con radius `12px` y sombra Mercury sutil.
- El contenido cliente arranca con `pt-16` bajo el topbar; todos los headers de cliente deben heredar ese aire desde el layout compartido.
- Gráficos dentro de cards grandes; el gráfico no vive como decoración separada.
- Acciones frecuentes en pills compactas arriba del contenido, no como CTAs enormes.
- Acento primario sigue siendo Cobalto Salto Ángel (`#2563EB`), no el color exacto de Mercury.

---

## 10. Componentes base (shadcn primitives)

Instalación obligatoria mes 1 del Bloque 1:

| Primitive | Uso principal |
|---|---|
| `Button` | Acciones (primary, secondary, ghost, destructive, link sizes: sm, md, lg) |
| `Input` | Campos de texto cortos |
| `Textarea` | Campos largos (KB, prompts, mensajes) |
| `Label` | Asociado a cada Input/Textarea (a11y) |
| `Select` | Dropdowns con opciones fijas |
| `Tabs` | Filtros de status, navegación dentro de página |
| `Card` | Contenedor genérico con padding, border, radius |
| `Badge` | Status pills (open, escalated, etc.) y count tags |
| `Dialog` | Modales (confirmar acción, ver detalle) |
| `Toast` (Sonner) | Notificaciones efímeras (success/error de acción) |
| `Skeleton` | Loading states |
| `Separator` | Líneas finas dentro de cards/listas |
| `Tooltip` | Hover hints sobre iconos/labels truncados |
| `DropdownMenu` | Menús contextuales (acción sobre fila, switcher) |
| `Sheet` | Paneles laterales (filtros avanzados, detalles cliente) |

**No se instala todo de una.** Se instala bajo demanda al refactorizar / construir cada pantalla. Pero la lista de arriba es la base esperada del Bloque 1.

---

## 11. Patrones

### 11.1 Tabla / lista

- Header con `text-xs uppercase tracking-wider` color `foreground-muted`.
- Filas con `border-b border-subtle`, hover `bg-surface-muted`.
- Padding por fila respeta densidad (`--density-row-y/x`).
- Filtros encima como `Tabs` con border bottom estilo `-mb-px border-b-2`.
- Empty state centrado, texto `foreground-muted`, no usar iconos grandes.
- Loading: `Skeleton` rows manteniendo altura para evitar layout shift.

### 11.2 Formulario

- `Label` arriba del campo, gap `space-1.5`.
- Helper text debajo del campo, gap `space-1`, color `foreground-muted`.
- Error state: borde `danger`, helper text `danger-foreground`, NO icono de error inline.
- Submit a la derecha; Cancel a la izquierda con variant `ghost`.
- Validación con react-hook-form + zod (decidido en architecture-web.md).

### 11.3 Card / panel

- Default: `bg-surface rounded-lg p-card-p` + sombra Mercury sutil.
- Eyebrow opcional arriba (`text-xs uppercase`).
- Heading h3 (`text-lg semibold`).
- Body con gap `space-3`.
- Acciones secundarias del card siempre en la esquina superior derecha.

### 11.4 Status badges

```
open       → cobalt-50 / cobalt-700      (info, activo)
pending    → warning-50 / warning-700    (esperando)
escalated  → danger-50 / danger-700      (atención humana)
resolved   → success-50 / success-700
closed     → neutral-100 / neutral-500
```

### 11.5 Vacío / error / loading

| Estado | Comportamiento |
|---|---|
| Vacío | Padding generoso (`space-12` y arriba), texto `foreground-muted`, sin ilustración (por ahora). |
| Error | Bloque `bg-danger-subtle text-danger-foreground rounded-md px-4 py-3` con mensaje claro y acción si la hay. |
| Loading | `Skeleton` con la altura aproximada del contenido final. No spinners (excepto botones en submit). |

### 11.6 Métricas / KPIs (super_admin home + dashboard cliente)

- Container `Card`.
- Eyebrow: nombre de la métrica (`text-xs uppercase tracking-wider foreground-muted`).
- Number: `text-3xl semibold` color `foreground`.
- Sub-label: tendencia o ventana (`text-xs foreground-muted`).
- Si hay cambio, signo + color: positivo cobalto (no verde), negativo danger.

---

## 12. Accesibilidad

Mínimos no negociables.

| Área | Regla |
|---|---|
| Contraste texto | 4.5:1 mínimo (WCAG AA). Verificar tokens `foreground-muted` sobre cada surface. |
| Contraste UI | 3:1 mínimo (borders activos, focus rings). |
| Focus visible | TODO control focuseable tiene outline cobalto, offset 2px. NUNCA `outline: none` sin reemplazo. |
| Labels | Todo input tiene `<Label>` asociado vía `htmlFor`. Placeholders NO son label. |
| Iconos | Si un botón es solo icono, `aria-label` obligatorio. |
| Tab order | Sigue el flujo visual de izq→der, arriba→abajo. |
| `prefers-reduced-motion` | Se respeta globalmente. |
| Idioma | `<html lang="es">` (ya está). |

---

## 13. Cómo aplicar (refactor checklist)

Cuando toques un componente existente:

1. **Reemplazar colores raw** (`text-neutral-900`, `bg-red-50`) por tokens semánticos (`text-foreground`, `bg-danger-subtle`).
2. **Reemplazar espaciados arbitrarios** (`p-5`, `gap-3`) por la escala (`p-card-p`, `gap-3` queda igual si está en la escala).
3. **Reemplazar radius hardcoded** (`rounded-xl`) por tokens (`rounded-md`).
4. **Verificar focus state**: outline cobalto presente en TODO control interactivo.
5. **Sustituir tags por primitives** cuando aplique: `<button>` → `<Button>`, `<input>` → `<Input>`, `<span class="badge">` → `<Badge>`.
6. **Tipografía**: si hay `font-weight` directo en Tailwind, verificar que esté en la escala (400/500/600/700 — nada más).
7. **Iconos**: confirmar que vienen de `lucide-react` y tienen tamaño de la escala (14/16/20/24).

---

## 14. Lo que NO está en scope para v1 (dashboard)

- Dark mode completo. Variables están preparadas para soportarlo, pero la implementación se posterga.
- Branding por tenant (logos, paletas del cliente). Se discutirá en Bloque 2.
- Ilustraciones y empty states ilustrados.
- Nuevas visualizaciones avanzadas fuera de las ya implementadas en dashboard cliente. Si se agregan charts, deben seguir los tokens existentes y reutilizar la librería ya instalada; no introducir una librería nueva sin una razón clara.
- Sistema de email templates visuales (`apps/api/services/email_templates`) — se cubre en sub-PR 1.5.

---

# Parte III — Landing (`apps/landing`)

## 15. Reglas para `apps/landing`

La landing pública usa Aceternity UI + Framer Motion. Aceternity trae módulos pre-hechos (hero animations, bento grids, scroll triggers, marquee de logos, pricing cards, etc.). NO los reescribimos; los **personalizamos vía tokens de la brand foundation**.

### 15.1 Lo que la landing hereda de la brand foundation

- **Color**: paleta completa de §3 — cobalto, neutrales stone, semánticos.
- **Tipografía**: Geist Sans + Geist Mono de §4. Misma escala de tamaños y pesos.
- **Spacing**: escala base 4px de §5 (Aceternity usa Tailwind, así que ya la entiende).
- **Radius**: tokens de §6.
- **Motion**: tokens y easing de §8 (especialmente `--motion-hero` para entradas de scroll).

### 15.2 Cómo se aplica

`apps/landing/app/globals.css` importa las mismas CSS variables que `apps/web/app/globals.css` (lo extraemos a un paquete compartido `packages/design-tokens/` cuando arranque el sub-PR de landing — por ahora, copia literal del bloque `@theme`).

Aceternity consume `bg-primary`, `text-foreground`, `border-border` directamente de Tailwind — al setear las variables, todos sus módulos se reskinanan sin tocar el código del módulo.

### 15.3 Lo que la landing NO toma del DESIGN.md

- Primitives shadcn (§10): no aplican. Landing usa los componentes Aceternity equivalentes.
- Patrones de tabla/formulario/card (§11): no aplican. Marketing tiene sus propios patrones (hero, pricing tier card, testimonial card, FAQ accordion).
- Densidad por contexto (§9): la landing es uniformemente "marketing-relaxed" — más generosa que `relaxed` del dashboard cliente.
- Refactor checklist (§13): no aplica, no hay componentes legacy que refactorizar.

### 15.4 Lo que SÍ es decisión de landing (no de este documento)

- Estructura de páginas (home / pricing / founding-partner / blog / security / about).
- Copy y mensajería.
- Sequencing de animaciones de scroll.
- Hero specifics (qué módulo Aceternity usar — bento, spotlight, sparkles, etc.).

Estos se documentan en `apps/landing/DESIGN.md` (subordinado a este) cuando arranquemos el sub-PR 1.8.

---

## 16. Cambios y versionado

Si vas a cambiar algo de este documento:

1. Discutilo en chat con Kenny ANTES de tocar.
2. Aprobado → editás `DESIGN.md` + bump de versión arriba.
3. Si afecta tokens o primitives, abrís PR independiente al refactor.
4. Cambios menores (typos, agregar un patrón faltante) van sin PR específico, pero quedan en el commit log.
