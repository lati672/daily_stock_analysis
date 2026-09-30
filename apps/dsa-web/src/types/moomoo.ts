export interface MoomooAccount {
  accountId: number;
  role: string;
  securityFirm: string;
  positionCount: number;
  currency: string;
  marketValue?: number | null;
  holdingPnl?: number | null;
  holdingPnlPct?: number | null;
  totalPnl?: number | null;
  totalPnlPct?: number | null;
  todayPnl?: number | null;
  todayPnlPct?: number | null;
}

export interface MoomooPosition {
  accountId: number;
  code: string;
  name: string;
  positionSide: string;
  quantity: number;
  availableQuantity?: number | null;
  costPrice?: number | null;
  currentPrice?: number | null;
  marketValue?: number | null;
  holdingPnl?: number | null;
  holdingPnlPct?: number | null;
  unrealizedPnl?: number | null;
  unrealizedPnlPct?: number | null;
  realizedPnl?: number | null;
  todayPnl?: number | null;
  todayChangePct?: number | null;
  currency: string;
  exchangeRateToReportingCurrency?: number | null;
}

export interface MoomooCashBalance {
  accountId: number;
  currency: string;
  cash: number;
  availableForWithdrawal?: number | null;
  netCashPower?: number | null;
}

export interface MoomooSnapshot {
  connected: boolean;
  provider: 'moomoo';
  host: string;
  port: number;
  readOnly: boolean;
  currency: string;
  totalMarketValue?: number | null;
  holdingPnl?: number | null;
  holdingPnlPct?: number | null;
  totalPnl?: number | null;
  totalPnlPct?: number | null;
  todayPnl?: number | null;
  todayPnlPct?: number | null;
  accounts: MoomooAccount[];
  positions: MoomooPosition[];
  cashBalances: MoomooCashBalance[];
}

export interface MoomooDailyReportStatus {
  enabled: boolean;
  usMarketOpenToday: boolean;
  scheduleTime: string;
  nextRunAt?: string | null;
  running: boolean;
  lastRunAt?: string | null;
  lastSuccessAt?: string | null;
  lastError?: string | null;
}

export interface MoomooDailyReportRunResult {
  accepted: boolean;
  running: boolean;
  reason?: string | null;
}
