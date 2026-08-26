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
}
