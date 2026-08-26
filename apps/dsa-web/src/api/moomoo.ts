import apiClient from './index';
import { toCamelCase } from './utils';
import type { MoomooSnapshot } from '../types/moomoo';

export const moomooApi = {
  async connect(): Promise<MoomooSnapshot> {
    const response = await apiClient.post<Record<string, unknown>>('/api/v1/portfolio/brokers/moomoo/connect');
    return toCamelCase<MoomooSnapshot>(response.data);
  },
};
