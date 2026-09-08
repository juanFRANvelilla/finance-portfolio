import { Component, inject, OnInit, signal } from '@angular/core';
import { Router, RouterOutlet, NavigationEnd } from '@angular/router';
import { filter } from 'rxjs';

import { MonthNavigatorComponent } from './features/dashboard/components/month-navigator/month-navigator.component';
import { PeriodStorageService } from './core/services/period-storage.service';

type ActiveView = 'dashboard' | 'investment-detail';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, MonthNavigatorComponent],
  template: `
    <div class="min-h-screen bg-slate-950 text-white">
      <!-- ═══════════════ HEADER GLOBAL ═══════════════ -->
      <header class="sticky top-0 z-40 border-b border-white/5 bg-slate-950/90 backdrop-blur-md">
        <div class="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-4">

          <!-- Branding -->
          <div>
            <span class="text-[10px] font-bold uppercase tracking-[0.2em] text-indigo-400">Finance Portfolio</span>
            <h1 class="text-xl font-bold leading-tight text-white">Panel de patrimonio personal</h1>
          </div>

          <!-- Navegador de mes -->
          <app-month-navigator
            [year]="year()"
            [month]="month()"
            (monthChange)="onMonthChange($event)"
          />

          <!-- View switcher -->
          <div class="flex items-center gap-1 self-start rounded-xl bg-slate-800/60 p-1 ring-1 ring-white/10">
            <button
              type="button"
              id="nav-dashboard"
              (click)="navigateTo('dashboard')"
              class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all duration-200"
              [class.bg-indigo-600]="activeView() === 'dashboard'"
              [class.shadow-lg]="activeView() === 'dashboard'"
              [class.text-white]="activeView() === 'dashboard'"
              [class.text-slate-400]="activeView() !== 'dashboard'"
              [class.hover:text-white]="activeView() !== 'dashboard'"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-3.5 w-3.5">
                <path fill-rule="evenodd" d="M9.293 2.293a1 1 0 0 1 1.414 0l7 7A1 1 0 0 1 17 11h-1v6a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1v-3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-6H3a1 1 0 0 1-.707-1.707l7-7Z" clip-rule="evenodd" />
              </svg>
              Vista general
            </button>
            <button
              type="button"
              id="nav-investment-detail"
              (click)="navigateTo('investment-detail')"
              class="flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-semibold transition-all duration-200"
              [class.bg-amber-600]="activeView() === 'investment-detail'"
              [class.shadow-lg]="activeView() === 'investment-detail'"
              [class.text-white]="activeView() === 'investment-detail'"
              [class.text-slate-400]="activeView() !== 'investment-detail'"
              [class.hover:text-white]="activeView() !== 'investment-detail'"
            >
              <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20" fill="currentColor" class="h-3.5 w-3.5">
                <path d="M15.5 2A1.5 1.5 0 0 0 14 3.5v13a1.5 1.5 0 0 0 3 0v-13A1.5 1.5 0 0 0 15.5 2ZM9.5 6A1.5 1.5 0 0 0 8 7.5v9a1.5 1.5 0 0 0 3 0v-9A1.5 1.5 0 0 0 9.5 6ZM3.5 10A1.5 1.5 0 0 0 2 11.5v5a1.5 1.5 0 0 0 3 0v-5A1.5 1.5 0 0 0 3.5 10Z" />
              </svg>
              Detalle de inversión
            </button>
          </div>

        </div>
      </header>

      <!-- ═══════════════ CONTENIDO DE RUTA ═══════════════ -->
      <router-outlet />
    </div>
  `,
})
export class App implements OnInit {
  private readonly router = inject(Router);
  private readonly periodStorage = inject(PeriodStorageService);

  private readonly stored = this.periodStorage.read();
  readonly year = signal<number>(this.stored.year);
  readonly month = signal<number>(this.stored.month);
  readonly activeView = signal<ActiveView>('dashboard');

  ngOnInit(): void {
    // Sincroniza el toggle con la URL actual en cada navegación
    this.router.events
      .pipe(filter((e) => e instanceof NavigationEnd))
      .subscribe((e) => {
        const url = (e as NavigationEnd).urlAfterRedirects;
        this.activeView.set(url.includes('investment-detail') ? 'investment-detail' : 'dashboard');
      });

    // Inicializa desde la URL actual (p.ej. recarga de página)
    const url = this.router.url;
    this.activeView.set(url.includes('investment-detail') ? 'investment-detail' : 'dashboard');
  }

  onMonthChange(next: { year: number; month: number }): void {
    this.year.set(next.year);
    this.month.set(next.month);
    this.periodStorage.save(next.year, next.month);

    // Navega a la vista activa con el nuevo periodo en los query params
    const path = this.activeView() === 'investment-detail' ? '/investment-detail' : '/';
    this.router.navigate([path], {
      queryParams: { year: next.year, month: next.month },
      replaceUrl: true,
    });
  }

  navigateTo(view: ActiveView): void {
    this.activeView.set(view);
    const path = view === 'investment-detail' ? '/investment-detail' : '/';
    this.router.navigate([path], {
      queryParams: { year: this.year(), month: this.month() },
    });
  }
}
