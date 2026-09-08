import {
  AfterViewInit,
  Component,
  ElementRef,
  OnChanges,
  OnDestroy,
  ViewChild,
  inject,
  input,
} from '@angular/core';
import { Chart, ChartConfiguration } from 'chart.js/auto';

import { TimelinePoint } from '../../../../core/models/monthly-record.model';
import { readCssVar } from '../../../../core/utils/read-css-var';

@Component({
  selector: 'app-timeline-chart',
  templateUrl: './timeline-chart.component.html',
  styleUrl: './timeline-chart.component.scss',
})
export class TimelineChartComponent implements AfterViewInit, OnChanges, OnDestroy {
  private readonly host = inject(ElementRef<HTMLElement>);

  readonly points = input.required<TimelinePoint[]>();

  @ViewChild('canvasRef') private readonly canvasRef!: ElementRef<HTMLCanvasElement>;
  private chart: Chart | null = null;

  ngAfterViewInit(): void {
    if (this.points().length > 0) {
      this.renderChart();
    }
  }

  ngOnChanges(): void {
    if (!this.canvasRef) {
      return;
    }
    if (this.points().length === 0) {
      this.chart?.destroy();
      this.chart = null;
      return;
    }
    if (this.chart) {
      this.updateChart();
    } else {
      this.renderChart();
    }
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  private labels(): string[] {
    const shortMonths = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic'];
    return this.points().map((p) => `${shortMonths[p.month - 1]} ${String(p.year).slice(-2)}`);
  }

  private chartTheme() {
    const el = this.host.nativeElement;
    return {
      netWorth: readCssVar(el, '--chart-net-worth-color', '#f97316'),
      invested: readCssVar(el, '--chart-invested-color', '#a855f7'),
      border: readCssVar(el, '--chart-border-color', '#0f172a'),
      netWorthFill: readCssVar(el, '--chart-net-worth-fill', 'rgba(249, 115, 22, 0.12)'),
      investedFill: readCssVar(el, '--chart-invested-fill', 'rgba(168, 85, 247, 0.12)'),
      axis: readCssVar(el, '--chart-axis-color', '#94a3b8'),
      grid: readCssVar(el, '--chart-grid-color', 'rgba(255,255,255,0.05)'),
    };
  }

  private renderChart(): void {
    const theme = this.chartTheme();
    const config: ChartConfiguration<'line'> = {
      type: 'line',
      data: {
        labels: this.labels(),
        datasets: [
          {
            label: 'Patrimonio neto',
            data: this.points().map((p) => p.total_net_worth),
            borderColor: theme.netWorth,
            backgroundColor: theme.netWorthFill,
            pointBackgroundColor: theme.netWorth,
            pointBorderColor: theme.border,
            pointBorderWidth: 2,
            pointRadius: 5,
            pointHoverRadius: 7,
            tension: 0.35,
            fill: false,
          },
          {
            label: 'Total invertido',
            data: this.points().map((p) => p.total_invested),
            borderColor: theme.invested,
            backgroundColor: theme.investedFill,
            pointBackgroundColor: theme.invested,
            pointBorderColor: theme.border,
            pointBorderWidth: 2,
            pointRadius: 5,
            pointHoverRadius: 7,
            tension: 0.35,
            fill: false,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            align: 'end',
            labels: {
              color: theme.axis,
              boxWidth: 12,
              usePointStyle: true,
              pointStyle: 'circle',
            },
          },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const value = ctx.parsed.y ?? 0;
                return ` ${ctx.dataset.label}: ${new Intl.NumberFormat('es-ES', {
                  style: 'currency',
                  currency: 'EUR',
                }).format(value)}`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: theme.grid },
            ticks: { color: theme.axis, font: { size: 11 } },
          },
          y: {
            grid: { color: theme.grid },
            ticks: {
              color: theme.axis,
              callback: (value) =>
                new Intl.NumberFormat('es-ES', {
                  style: 'currency',
                  currency: 'EUR',
                  maximumFractionDigits: 0,
                }).format(Number(value)),
            },
          },
        },
      },
    };

    this.chart = new Chart(this.canvasRef.nativeElement, config);
  }

  private updateChart(): void {
    if (!this.chart) {
      return;
    }
    this.chart.data.labels = this.labels();
    this.chart.data.datasets[0].data = this.points().map((p) => p.total_net_worth);
    this.chart.data.datasets[1].data = this.points().map((p) => p.total_invested);
    this.chart.update();
  }
}
