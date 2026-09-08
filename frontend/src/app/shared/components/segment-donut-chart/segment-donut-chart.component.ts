import {
  AfterViewInit,
  Component,
  ElementRef,
  OnChanges,
  OnDestroy,
  ViewChild,
  inject,
  input,
  output,
} from '@angular/core';
import { Chart, ChartConfiguration } from 'chart.js/auto';

import { EurCurrencyPipe } from '../../../core/pipes/eur-currency.pipe';
import { readCssVar } from '../../../core/utils/read-css-var';

export interface DonutSegment {
  id: string;
  label: string;
  value: number;
  color: string;
}

@Component({
  selector: 'app-segment-donut-chart',
  imports: [EurCurrencyPipe],
  templateUrl: './segment-donut-chart.component.html',
  styleUrl: './segment-donut-chart.component.scss',
})
export class SegmentDonutChartComponent implements AfterViewInit, OnChanges, OnDestroy {
  private readonly host = inject(ElementRef<HTMLElement>);

  readonly segments = input.required<DonutSegment[]>();
  readonly centerLabel = input<string>('');
  readonly centerValue = input<number | null>(null);
  readonly clickable = input<boolean>(false);
  readonly segmentClick = output<string>();

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

  onLegendClick(id: string): void {
    if (this.clickable()) {
      this.segmentClick.emit(id);
    }
  }

  private chartBorderColor(): string {
    return readCssVar(this.host.nativeElement, '--chart-border-color', '#0f172a');
  }

  private renderChart(): void {
    const borderColor = this.chartBorderColor();
    const config: ChartConfiguration<'doughnut'> = {
      type: 'doughnut',
      data: {
        labels: this.segments().map((s) => s.label),
        datasets: [
          {
            data: this.segments().map((s) => s.value),
            backgroundColor: this.segments().map((s) => s.color),
            borderColor,
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
    this.chart.data.labels = this.segments().map((s) => s.label);
    this.chart.data.datasets[0].data = this.segments().map((s) => s.value);
    this.chart.data.datasets[0].backgroundColor = this.segments().map((s) => s.color);
    this.chart.update();
  }
}
