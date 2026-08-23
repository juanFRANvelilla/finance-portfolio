import { Routes } from '@angular/router';

export const routes: Routes = [
  {
    path: '',
    loadComponent: () =>
      import('./features/dashboard/dashboard.component').then((m) => m.DashboardComponent),
  },
  {
    path: 'investment-detail',
    loadComponent: () =>
      import('./features/investment-detail/investment-detail.component').then(
        (m) => m.InvestmentDetailComponent,
      ),
  },
  { path: '**', redirectTo: '' },
];
