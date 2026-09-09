import { Component, inject, OnInit, signal } from '@angular/core';
import { Router, RouterOutlet, NavigationEnd } from '@angular/router';
import { filter } from 'rxjs';

import { MonthNavigatorComponent } from './features/dashboard/components/month-navigator/month-navigator.component';
import { PeriodStorageService } from './core/services/period-storage.service';

type ActiveView = 'dashboard' | 'investment-detail' | 'investment-ledger';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, MonthNavigatorComponent],
  templateUrl: './app.html',
  styleUrl: './app.scss',
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
        this.activeView.set(this.viewFromUrl((e as NavigationEnd).urlAfterRedirects));
      });

    // Inicializa desde la URL actual (p.ej. recarga de página)
    this.activeView.set(this.viewFromUrl(this.router.url));
  }

  private viewFromUrl(url: string): ActiveView {
    if (url.includes('investment-ledger')) {
      return 'investment-ledger';
    }
    if (url.includes('investment-detail')) {
      return 'investment-detail';
    }
    return 'dashboard';
  }

  private pathForView(view: ActiveView): string {
    switch (view) {
      case 'investment-detail':
        return '/investment-detail';
      case 'investment-ledger':
        return '/investment-ledger';
      default:
        return '/';
    }
  }

  onMonthChange(next: { year: number; month: number }): void {
    this.year.set(next.year);
    this.month.set(next.month);
    this.periodStorage.save(next.year, next.month);

    // Navega a la vista activa con el nuevo periodo en los query params
    this.router.navigate([this.pathForView(this.activeView())], {
      queryParams: { year: next.year, month: next.month },
      replaceUrl: true,
    });
  }

  navigateTo(view: ActiveView): void {
    this.activeView.set(view);
    this.router.navigate([this.pathForView(view)], {
      queryParams: { year: this.year(), month: this.month() },
    });
  }
}
