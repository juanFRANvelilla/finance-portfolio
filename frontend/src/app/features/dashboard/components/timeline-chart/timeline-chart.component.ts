import {
  AfterViewInit,
  Component,
  ElementRef,
  OnChanges,
  OnDestroy,
  ViewChild,
  input,
} from '@angular/core';
import { Chart, ChartConfiguration } from 'chart.js/auto';

import { TimelinePoint } from '../../../../core/models/monthly-record.model';

const COLOR_NET_WORTH = '#f97316';
const COLOR_INVESTED = '#a855f7';

@Component({
  selector: 'app-timeline-chart',
  templateUrl: './timeline-chart.component.html',
})
export class TimelineChartComponent implements AfterViewInit, OnChanges, OnDestroy {
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

  private renderChart(): void {
    const config: ChartConfiguration<'line'> = {
      type: 'line',
      data: {
        labels: this.labels(),
        datasets: [
          {
            label: 'Patrimonio neto',
            data: this.points().map((p) => p.total_net_worth),
            borderColor: COLOR_NET_WORTH,
            backgroundColor: 'rgba(249, 115, 22, 0.12)',
            pointBackgroundColor: COLOR_NET_WORTH,
            pointBorderColor: '#0f172a',
            pointBorderWidth: 2,
            pointRadius: 5,
            pointHoverRadius: 7,
            tension: 0.35,
            fill: false,
          },
          {
            label: 'Total invertido',
            data: this.points().map((p) => p.total_invested),
            borderColor: COLOR_INVESTED,
            backgroundColor: 'rgba(168, 85, 247, 0.12)',
            pointBackgroundColor: COLOR_INVESTED,
            pointBorderColor: '#0f172a',
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
              color: '#94a3b8',
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
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: { color: '#94a3b8', font: { size: 11 } },
          },
          y: {
            grid: { color: 'rgba(255,255,255,0.05)' },
            ticks: {
              color: '#94a3b8',
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
