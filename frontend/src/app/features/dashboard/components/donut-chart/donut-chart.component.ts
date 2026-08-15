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

import { EurCurrencyPipe } from '../../../../core/pipes/eur-currency.pipe';

@Component({
  selector: 'app-donut-chart',
  imports: [EurCurrencyPipe],
  templateUrl: './donut-chart.component.html',
})
export class DonutChartComponent implements AfterViewInit, OnChanges, OnDestroy {
  readonly totalLiquid = input.required<number>();
  readonly totalInvested = input.required<number>();
  readonly totalNetWorth = input.required<number>();

  @ViewChild('canvasRef') private readonly canvasRef!: ElementRef<HTMLCanvasElement>;
  private chart: Chart | null = null;

  ngAfterViewInit(): void {
    this.renderChart();
  }

  ngOnChanges(): void {
    if (this.chart) {
      this.updateChart();
    }
  }

  ngOnDestroy(): void {
    this.chart?.destroy();
  }

  private renderChart(): void {
    const config: ChartConfiguration<'doughnut'> = {
      type: 'doughnut',
      data: {
        labels: ['Líquido', 'Invertido'],
        datasets: [
          {
            data: [this.totalLiquid(), this.totalInvested()],
            backgroundColor: ['#38bdf8', '#a855f7'],
            borderColor: '#0f172a',
            borderWidth: 3,
            hoverOffset: 6,
          },
        ],
      },
      options: {
        cutout: '72%',
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (ctx) => {
                const value = ctx.parsed as number;
                return ` ${ctx.label}: ${new Intl.NumberFormat('es-ES', {
                  style: 'currency',
                  currency: 'EUR',
                }).format(value)}`;
              },
            },
          },
        },
      },
    };

    this.chart = new Chart(this.canvasRef.nativeElement, config);
  }

  private updateChart(): void {
    if (!this.chart) return;
    this.chart.data.datasets[0].data = [this.totalLiquid(), this.totalInvested()];
    this.chart.update();
  }
}
