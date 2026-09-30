import apiClient from './index';
import { toCamelCase } from './utils';
import type { MoomooDailyReportRunResult, MoomooDailyReportStatus, MoomooSnapshot } from '../types/moomoo';

export const moomooApi = {
  async connect(): Promise<MoomooSnapshot> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/portfolio/brokers/moomoo/connect');
    return toCamelCase<MoomooSnapshot>(response.data);
  },
  async getDailyReportStatus(): Promise<MoomooDailyReportStatus> {
    const response = await apiClient.get<Record<string, unknown>>('/api/v1/portfolio/brokers/moomoo/daily-report/status');
    return toCamelCase<MoomooDailyReportStatus>(response.data);
  },
  async updateDailyReportSettings(enabled: boolean): Promise<MoomooDailyReportStatus> {
    const response = await apiClient.put<Record<string, unknown>>(
      '/api/v1/portfolio/brokers/moomoo/daily-report/settings',
      { enabled },
    );
    return toCamelCase<MoomooDailyReportStatus>(response.data);
  },
  async runDailyReportNow(): Promise<MoomooDailyReportRunResult> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/portfolio/brokers/moomoo/daily-report/run');
    return toCamelCase<MoomooDailyReportRunResult>(response.data);
  },
};
