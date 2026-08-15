# Finance Portfolio · Frontend

SPA en **Angular 21 (standalone) + Tailwind CSS + Chart.js** para el dashboard de patrimonio personal. Generado con Angular CLI.

## Configuración

La URL de la API se define en `src/environments/environment.ts` / `environment.development.ts` (por defecto `http://localhost:8000/api`).

## Arranque rápido

```bash
./run.sh
```

O manualmente:

```bash
npm install
ng serve
```

Una vez arrancado, abre `http://localhost:4200/`. La aplicación se recarga automáticamente al modificar el código. Asegúrate de que el backend esté corriendo en `http://localhost:8000` para que el dashboard cargue datos.

## Estructura relevante

```
src/app/
  core/
    models/       # Interfaces TypeScript (Entity, MonthlyRecord, ...)
    services/     # FinanceApiService (llamadas HTTP al backend)
    pipes/        # EurCurrencyPipe (formato de moneda es-ES)
  features/
    dashboard/    # Componente principal + subcomponentes (navegador de meses,
                   # donut chart, badge de diff, formulario de saldos)
```

## Development server

To start a local development server, run:

```bash
ng serve
```

Once the server is running, open your browser and navigate to `http://localhost:4200/`. The application will automatically reload whenever you modify any of the source files.

## Code scaffolding

Angular CLI includes powerful code scaffolding tools. To generate a new component, run:

```bash
ng generate component component-name
```

For a complete list of available schematics (such as `components`, `directives`, or `pipes`), run:

```bash
ng generate --help
```

## Building

To build the project run:

```bash
ng build
```

This will compile your project and store the build artifacts in the `dist/` directory. By default, the production build optimizes your application for performance and speed.

## Running unit tests

To execute unit tests with the [Vitest](https://vitest.dev/) test runner, use the following command:

```bash
ng test
```

## Running end-to-end tests

For end-to-end (e2e) testing, run:

```bash
ng e2e
```

Angular CLI does not come with an end-to-end testing framework by default. You can choose one that suits your needs.

## Additional Resources

For more information on using the Angular CLI, including detailed command references, visit the [Angular CLI Overview and Command Reference](https://angular.dev/tools/cli) page.
