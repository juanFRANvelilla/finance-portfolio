import { Component, inject, OnInit, signal } from '@angular/core';
import { Router, RouterOutlet, NavigationEnd } from '@angular/router';
import { filter } from 'rxjs';

import { MonthNavigatorComponent } from './features/dashboard/components/month-navigator/month-navigator.component';
import { PeriodStorageService } from './core/services/period-storage.service';

type ActiveView = 'dashboard' | 'investment-detail';

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
