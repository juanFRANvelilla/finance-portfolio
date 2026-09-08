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

import { EurCurrencyPipe } from '../../../../core/pipes/eur-currency.pipe';
import { readCssVar } from '../../../../core/utils/read-css-var';

@Component({
  selector: 'app-donut-chart',
  imports: [EurCurrencyPipe],
  templateUrl: './donut-chart.component.html',
  styleUrl: './donut-chart.component.scss',
})
export class DonutChartComponent implements AfterViewInit, OnChanges, OnDestroy {
  private readonly host = inject(ElementRef<HTMLElement>);

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

  private chartColors(): { liquid: string; invested: string; border: string } {
    const el = this.host.nativeElement;
    return {
      liquid: readCssVar(el, '--chart-liquid-color', '#38bdf8'),
      invested: readCssVar(el, '--chart-invested-color', '#a855f7'),
      border: readCssVar(el, '--chart-border-color', '#0f172a'),
    };
  }

  private renderChart(): void {
    const colors = this.chartColors();
    const config: ChartConfiguration<'doughnut'> = {
      type: 'doughnut',
      data: {
        labels: ['Líquido', 'Invertido'],
        datasets: [
          {
            data: [this.totalLiquid(), this.totalInvested()],
            backgroundColor: [colors.liquid, colors.invested],
            borderColor: colors.border,
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
