import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { ChevronDown, ChevronUp, Link2, RefreshCw, ShieldCheck, Sparkles, Unplug } from 'lucide-react';
import { moomooApi } from '../api/moomoo';
import { AppPage, Card, InlineAlert, PageHeader, SectionCard } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { MoomooSnapshot } from '../types/moomoo';

type MarketKey = 'us' | 'hk' | 'other';
type SortKey = 'code' | 'todayChangePct' | 'quantity' | 'costPrice' | 'currentPrice' | 'marketValue' | 'weight' | 'todayPnl' | 'holdingPnl' | 'unrealizedPnl' | 'realizedPnl';
type SortDirection = 'desc' | 'asc';
type SortConfig = { key: SortKey; direction: SortDirection };
const DEFAULT_MARKET_SORT: SortConfig = { key: 'todayChangePct', direction: 'desc' };

type MarketSection = {
  key: MarketKey;
  title: string;
  subtitle: string;
  positions: MoomooSnapshot['positions'];
  currency: string;
  marketValue: number | null;
  holdingPnl: number | null;
  todayPnl: number | null;
};

function optionalNumber(value: number | null | undefined, locale: string, digits = 2): string {
  return value == null ? '—' : new Intl.NumberFormat(locale, { maximumFractionDigits: digits }).format(value);
}

function formatMoney(value: number | null | undefined, currency: string, locale: string, signed = false): string {
  if (value == null) return '—';
  const isNeutral = Math.abs(value) < 0.005;
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currency || 'USD',
    currencyDisplay: currency.toUpperCase() === 'HKD' ? 'code' : 'narrowSymbol',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: signed && !isNeutral ? 'always' : 'auto',
  }).format(isNeutral ? 0 : value);
}

function formatPositionMoney(value: number | null | undefined, currency: string, locale: string, signed = false): string {
  if (currency.toUpperCase() !== 'HKD') return formatMoney(value, currency, locale, signed);
  if (value == null) return '—';
  const isNeutral = Math.abs(value) < 0.005;
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: signed && !isNeutral ? 'always' : 'auto',
  }).format(isNeutral ? 0 : value);
}

function formatSignedPercent(value: number | null | undefined, locale: string): string {
  if (value == null) return '—';
  const isNeutral = Math.abs(value) < 0.005;
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
    signDisplay: isNeutral ? 'auto' : 'always',
  }).format(isNeutral ? 0 : value) + '%';
}

function pnlTone(value: number | null | undefined): string {
  if (value == null || Math.abs(value) < 0.005) return 'text-secondary-text';
  return value > 0 ? 'text-success' : 'text-danger';
}

function calculateTodayPnl(positions: MoomooSnapshot['positions'], currency: string): number | null {
  if (positions.length === 0) return 0;
  if (positions.some((position) => position.currency.toUpperCase() !== currency.toUpperCase())) return null;
  if (positions.some((position) => position.todayPnl == null)) return null;
  return positions.reduce((total, position) => total + (position.todayPnl ?? 0), 0);
}

function sumPositionField(
  positions: MoomooSnapshot['positions'],
  select: (position: MoomooSnapshot['positions'][number]) => number | null | undefined,
): number | null {
  if (positions.some((position) => select(position) == null)) return null;
  return positions.reduce((total, position) => total + (select(position) ?? 0), 0);
}

function summarizeMarket(positions: MoomooSnapshot['positions'], fallbackCurrency: string) {
  const currencies = [...new Set(positions.map((position) => position.currency?.toUpperCase()).filter(Boolean))];
  const hasSingleCurrency = currencies.length <= 1;
  return {
    currency: currencies[0] ?? fallbackCurrency,
    marketValue: hasSingleCurrency ? sumPositionField(positions, (position) => position.marketValue) : null,
    holdingPnl: hasSingleCurrency ? sumPositionField(positions, (position) => position.holdingPnl) : null,
    todayPnl: hasSingleCurrency ? sumPositionField(positions, (position) => position.todayPnl) : null,
  };
}

function calculatePnlPercentage(pnl: number | null | undefined, currentValue: number | null | undefined): number | null {
  if (pnl == null || currentValue == null) return null;
  const previousValue = currentValue - pnl;
  return previousValue > 0 ? pnl / previousValue * 100 : null;
}

function errorMessage(error: unknown, fallback: string): string {
  if (axios.isAxiosError(error)) {
    const detail = error.response?.data?.detail;
    if (typeof detail === 'string') return detail;
    if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message;
    return error.message || fallback;
  }
  return error instanceof Error ? error.message : fallback;
}

function marketPrefix(code: string): string {
  return code.split('.', 1)[0]?.toUpperCase() ?? '';
}

function displayCode(code: string): string {
  const separatorIndex = code.indexOf('.');
  return separatorIndex >= 0 ? code.slice(separatorIndex + 1) : code;
}

function analysisCode(code: string): string {
  const [market, symbol = code] = code.toUpperCase().split('.', 2);
  if (market === 'HK') return `HK${symbol.padStart(5, '0')}`;
  return symbol;
}

function positionAnalysisHref(position: MoomooSnapshot['positions'][number]): string {
  const params = new URLSearchParams({
    stock: analysisCode(position.code),
    name: position.name || '',
    moomoo: 'position',
    new: '1',
  });
  return `/chat?${params.toString()}`;
}

function sortMarketPositions(
  positions: MoomooSnapshot['positions'],
  config: SortConfig,
  totalMarketValue: number | null,
): MoomooSnapshot['positions'] {
  const numericValue = (position: MoomooSnapshot['positions'][number]): number | null => {
    if (config.key === 'quantity') return position.quantity;
    if (config.key === 'todayChangePct') return position.todayChangePct ?? null;
    if (config.key === 'costPrice') return position.costPrice ?? null;
    if (config.key === 'currentPrice') return position.currentPrice ?? null;
    if (config.key === 'todayPnl') return position.todayPnl ?? null;
    if (config.key === 'holdingPnl') return position.holdingPnl ?? null;
    if (config.key === 'unrealizedPnl') return position.unrealizedPnl ?? null;
    if (config.key === 'realizedPnl') return position.realizedPnl ?? null;
    if (config.key === 'marketValue') return position.marketValue ?? null;
    if (config.key === 'weight') {
      return totalMarketValue != null && totalMarketValue > 0 && position.marketValue != null
        ? position.marketValue / totalMarketValue
        : null;
    }
    return null;
  };

  return [...positions].sort((left, right) => {
    if (config.key === 'code') {
      const comparison = displayCode(left.code).localeCompare(displayCode(right.code));
      return config.direction === 'asc' ? comparison : -comparison;
    }
    const leftValue = numericValue(left);
    const rightValue = numericValue(right);
    if (leftValue == null && rightValue == null) return displayCode(left.code).localeCompare(displayCode(right.code));
    if (leftValue == null) return 1;
    if (rightValue == null) return -1;
    if (leftValue !== rightValue) {
      return config.direction === 'asc' ? leftValue - rightValue : rightValue - leftValue;
    }
    const leftWeight = totalMarketValue != null && totalMarketValue > 0 ? (left.marketValue ?? 0) / totalMarketValue : 0;
    const rightWeight = totalMarketValue != null && totalMarketValue > 0 ? (right.marketValue ?? 0) / totalMarketValue : 0;
    if (leftWeight !== rightWeight) return rightWeight - leftWeight;
    return displayCode(left.code).localeCompare(displayCode(right.code));
  });
}

type SortableHeaderProps = {
  label: string;
  marketTitle: string;
  sortKey: SortKey;
  config: SortConfig;
  align?: 'left' | 'right';
  onSort: (key: SortKey) => void;
};

function SortableHeader({ label, marketTitle, sortKey, config, align = 'right', onSort }: SortableHeaderProps) {
  const active = config.key === sortKey;
  const sortState = active ? (config.direction === 'asc' ? '升序' : '降序') : '未排序';
  return (
    <th className="px-3 py-3" aria-sort={active ? (config.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button
        type="button"
        className={`flex w-full items-center gap-1 transition-colors hover:text-foreground ${align === 'right' ? 'justify-end' : 'justify-start'}`}
        aria-label={`${marketTitle}：${label}，${sortState}`}
        onClick={() => onSort(sortKey)}
      >
        <span>{label}</span>
        <span className="flex flex-col -space-y-1" aria-hidden="true">
          <ChevronUp className={`h-3 w-3 ${active && config.direction === 'asc' ? 'text-orange-500' : 'text-muted-text/60'}`} />
          <ChevronDown className={`h-3 w-3 ${active && config.direction === 'desc' ? 'text-orange-500' : 'text-muted-text/60'}`} />
        </span>
      </button>
    </th>
  );
}

const AccountPage = () => {
  const { language } = useUiLanguage();
  const zh = language === 'zh';
  const locale = zh ? 'zh-CN' : 'en-US';
  const [snapshot, setSnapshot] = useState<MoomooSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accountId, setAccountId] = useState<number | 'all'>('all');
  const [updatedAt, setUpdatedAt] = useState<Date | null>(null);
  const [marketSorts, setMarketSorts] = useState<Record<MarketKey, SortConfig | null>>({
    us: null,
    hk: null,
    other: null,
  });

  const positions = useMemo(() => {
    if (!snapshot || accountId === 'all') return snapshot?.positions ?? [];
    return snapshot.positions.filter((item) => item.accountId === accountId);
  }, [accountId, snapshot]);

  const marketSections = useMemo<MarketSection[]>(() => {
    const usPositions = positions.filter((item) => marketPrefix(item.code) === 'US');
    const hkPositions = positions.filter((item) => marketPrefix(item.code) === 'HK');
    const otherPositions = positions.filter((item) => !['US', 'HK'].includes(marketPrefix(item.code)));
    return [
      {
        key: 'us',
        title: zh ? '美股持仓' : 'US positions',
        subtitle: zh ? `${usPositions.length} 项` : `${usPositions.length} positions`,
        positions: usPositions,
        ...summarizeMarket(usPositions, 'USD'),
      },
      {
        key: 'hk',
        title: zh ? '港股持仓' : 'Hong Kong positions',
        subtitle: zh ? `${hkPositions.length} 项` : `${hkPositions.length} positions`,
        positions: hkPositions,
        ...summarizeMarket(hkPositions, 'HKD'),
      },
      ...(otherPositions.length > 0 ? [{
        key: 'other' as const,
        title: zh ? '其他市场持仓' : 'Other market positions',
        subtitle: zh ? `${otherPositions.length} 项` : `${otherPositions.length} positions`,
        positions: otherPositions,
        ...summarizeMarket(otherPositions, snapshot?.currency ?? 'USD'),
      }] : []),
    ];
  }, [positions, snapshot?.currency, zh]);

  const portfolioSummary = useMemo(() => {
    const selectedAccount = accountId === 'all'
      ? null
      : snapshot?.accounts.find((account) => account.accountId === accountId) ?? null;
    const positionsMarketValue = positions.reduce(
      (total, position) => total + (position.marketValue ?? 0),
      0,
    );
    const marketValue = selectedAccount?.marketValue
      ?? (accountId === 'all' ? snapshot?.totalMarketValue : null)
      ?? positionsMarketValue;
    const currency = selectedAccount?.currency ?? snapshot?.currency ?? 'USD';
    const todayPnl = selectedAccount?.todayPnl
      ?? (accountId === 'all' ? snapshot?.todayPnl : null)
      ?? calculateTodayPnl(positions, currency);
    return {
      currency,
      marketValue,
      holdingPnl: selectedAccount?.holdingPnl ?? (accountId === 'all' ? snapshot?.holdingPnl : null),
      holdingPnlPct: selectedAccount?.holdingPnlPct ?? (accountId === 'all' ? snapshot?.holdingPnlPct : null),
      todayPnl,
      todayPnlPct: selectedAccount?.todayPnlPct
        ?? (accountId === 'all' ? snapshot?.todayPnlPct : null)
        ?? calculatePnlPercentage(todayPnl, marketValue),
    };
  }, [accountId, positions, snapshot]);

  const connect = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await moomooApi.connect();
      setSnapshot(result);
      setUpdatedAt(new Date());
      setAccountId((current) => (
        current !== 'all' && !result.accounts.some((item) => item.accountId === current)
          ? 'all'
          : current
      ));
    } catch (err) {
      setError(errorMessage(err, zh ? '无法连接 Moomoo OpenD' : 'Unable to connect to Moomoo OpenD'));
    } finally {
      setLoading(false);
    }
  }, [zh]);

  useEffect(() => {
    void connect();
  }, [connect]);

  return (
    <AppPage>
      <div className="space-y-5">
        <PageHeader
          eyebrow="Moomoo OpenD"
          title={zh ? '账户' : 'Account'}
          description={zh ? '通过后端只读连接已登录的 Moomoo OpenD，查看真实账户持仓。' : 'Connect to a signed-in Moomoo OpenD through the backend and view real account positions in read-only mode.'}
          actions={(
            <button type="button" className="btn-primary inline-flex items-center gap-2" disabled={loading} onClick={() => void connect()}>
              {loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />}
              {loading ? (zh ? '刷新中…' : 'Refreshing…') : (zh ? '刷新持仓' : 'Refresh positions')}
            </button>
          )}
        />

        <InlineAlert
          variant="info"
          title={zh ? '安全边界' : 'Security boundary'}
          message={zh ? '页面不会接收 Moomoo 密码或交易解锁密码。请先在运行后端的设备上启动并登录 OpenD；连接参数来自服务端 FUTU_OPEND_HOST、FUTU_OPEND_PORT、FUTU_SECURITY_FIRM 和可选的 FUTU_ACC_ID。' : 'This page never accepts a Moomoo password or trading unlock password. Start and sign in to OpenD on the backend host first; connection settings come from server-side FUTU_* configuration.'}
        />

        {error ? <InlineAlert variant="danger" title={zh ? '连接失败' : 'Connection failed'} message={error} /> : null}

        {!snapshot ? (
          <Card padding="lg" className="flex min-h-64 flex-col items-center justify-center text-center">
            <Unplug className="h-10 w-10 text-muted-text" />
            <h2 className="mt-4 text-lg font-semibold text-foreground">{zh ? '尚未连接账户' : 'No account connected'}</h2>
            <p className="mt-2 max-w-lg text-sm text-secondary-text">{zh ? '确认 OpenD 已启动并登录，然后点击“连接 Moomoo”。' : 'Make sure OpenD is running and signed in, then select “Connect Moomoo”.'}</p>
          </Card>
        ) : (
          <>
            <Card padding="lg">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <p className="label-uppercase">{zh ? '账户资产' : 'Account assets'}</p>
                  <h2 className="mt-1 text-lg font-semibold text-foreground">{zh ? '投资组合' : 'Portfolio'}</h2>
                </div>
                <div className="flex items-center gap-2 text-xs text-secondary-text">
                  <ShieldCheck className="h-4 w-4 text-success" />
                  <span>{zh ? '已连接 · 只读' : 'Connected · Read-only'}</span>
                  <span>·</span>
                  <span>{snapshot.host}:{snapshot.port}</span>
                  {updatedAt ? <span>· {zh ? '刷新于 ' : 'Updated '}{updatedAt.toLocaleTimeString(locale)}</span> : null}
                </div>
              </div>
              <div className="mt-6 grid gap-6 border-t border-border/50 pt-5 sm:grid-cols-3 sm:gap-8">
                <div>
                  <p className="text-xs font-medium text-secondary-text">{zh ? '总市值' : 'Total market value'}</p>
                  <p className="mt-2 text-3xl font-semibold tracking-tight text-foreground tabular-nums">
                    {formatMoney(portfolioSummary.marketValue, portfolioSummary.currency, locale)}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-secondary-text">{zh ? '持仓盈亏' : 'Position P/L'}</p>
                  <p className={`mt-2 text-2xl font-semibold tabular-nums ${pnlTone(portfolioSummary.holdingPnl)}`}>
                    {formatMoney(portfolioSummary.holdingPnl, portfolioSummary.currency, locale, true)}
                  </p>
                  <p className={`mt-1 text-sm font-medium tabular-nums ${pnlTone(portfolioSummary.holdingPnlPct)}`}>
                    {formatSignedPercent(portfolioSummary.holdingPnlPct, locale)}
                  </p>
                </div>
                <div>
                  <p className="text-xs font-medium text-secondary-text">{zh ? '今日盈亏' : "Today's P/L"}</p>
                  <p className={`mt-2 text-2xl font-semibold tabular-nums ${pnlTone(portfolioSummary.todayPnl)}`}>
                    {formatMoney(portfolioSummary.todayPnl, portfolioSummary.currency, locale, true)}
                  </p>
                  <p className={`mt-1 text-sm font-medium tabular-nums ${pnlTone(portfolioSummary.todayPnlPct)}`}>
                    {formatSignedPercent(portfolioSummary.todayPnlPct, locale)}
                  </p>
                  <a
                    href="/chat?moomoo=portfolio&task=today-attribution&new=1"
                    className="mt-2 inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80"
                  >
                    <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
                    {zh ? 'AI 归因' : 'AI attribution'}
                  </a>
                </div>
              </div>
            </Card>

            {snapshot.accounts.length > 1 ? (
              <div className="flex justify-end">
                <select className="input-base min-w-40" aria-label={zh ? '账户筛选' : 'Account filter'} value={accountId} onChange={(event) => setAccountId(event.target.value === 'all' ? 'all' : Number(event.target.value))}>
                  <option value="all">{zh ? '全部账户' : 'All accounts'}</option>
                  {snapshot.accounts.map((account) => <option key={account.accountId} value={account.accountId}>#{account.accountId} · {account.positionCount}</option>)}
                </select>
              </div>
            ) : null}

            {marketSections.map((section) => {
              const sortConfig = marketSorts[section.key] ?? DEFAULT_MARKET_SORT;
              const sortedPositions = sortMarketPositions(section.positions, sortConfig, section.marketValue);
              const setSortKey = (key: SortKey) => setMarketSorts((current) => {
                const currentSort = current[section.key];
                if (!currentSort || currentSort.key !== key) {
                  return { ...current, [section.key]: { key, direction: 'desc' } };
                }
                if (currentSort.direction === 'desc') {
                  return { ...current, [section.key]: { key, direction: 'asc' } };
                }
                return { ...current, [section.key]: null };
              });
              return (
              <SectionCard
                key={section.key}
                title={section.title}
                subtitle={section.subtitle}
              >
                <div className="mb-4 grid gap-4 border-y border-border/50 py-3 sm:grid-cols-3 sm:gap-6">
                  <div>
                    <p className="text-xs font-medium text-secondary-text">{zh ? '总市值' : 'Total market value'}</p>
                    <p className="mt-1 text-lg font-semibold text-foreground tabular-nums">
                      {formatMoney(section.marketValue, section.currency, locale)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-secondary-text">{zh ? '持仓盈亏' : 'Position P/L'}</p>
                    <p className={`mt-1 text-lg font-semibold tabular-nums ${pnlTone(section.holdingPnl)}`}>
                      {formatMoney(section.holdingPnl, section.currency, locale, true)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-secondary-text">{zh ? '今日盈亏' : "Today's P/L"}</p>
                    <p className={`mt-1 text-lg font-semibold tabular-nums ${pnlTone(section.todayPnl)}`}>
                      {formatMoney(section.todayPnl, section.currency, locale, true)}
                    </p>
                  </div>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[1320px] text-left text-sm">
                    <thead className="border-b border-border/70 text-xs text-secondary-text"><tr>
                      <SortableHeader label={zh ? '证券' : 'Security'} marketTitle={section.title} sortKey="code" config={sortConfig} align="left" onSort={setSortKey} />
                      <SortableHeader label={zh ? '今日涨幅' : 'Day change'} marketTitle={section.title} sortKey="todayChangePct" config={sortConfig} onSort={setSortKey} />
                      <SortableHeader label={zh ? '数量' : 'Qty'} marketTitle={section.title} sortKey="quantity" config={sortConfig} onSort={setSortKey} />
                      <SortableHeader label={zh ? '平均成本' : 'Average cost'} marketTitle={section.title} sortKey="costPrice" config={sortConfig} onSort={setSortKey} />
                      <SortableHeader label={zh ? '现价' : 'Price'} marketTitle={section.title} sortKey="currentPrice" config={sortConfig} onSort={setSortKey} />
                      <SortableHeader label={zh ? '市值' : 'Market value'} marketTitle={section.title} sortKey="marketValue" config={sortConfig} onSort={setSortKey} />
                      <SortableHeader label={zh ? '仓位' : 'Weight'} marketTitle={section.title} sortKey="weight" config={sortConfig} onSort={setSortKey} />
                      <SortableHeader label={zh ? '今日盈亏' : "Today's P/L"} marketTitle={section.title} sortKey="todayPnl" config={sortConfig} onSort={setSortKey} />
                      <SortableHeader label={zh ? '持仓盈亏' : 'Position P/L'} marketTitle={section.title} sortKey="holdingPnl" config={sortConfig} onSort={setSortKey} />
                      <SortableHeader label={zh ? '未实现盈亏' : 'Unrealized P/L'} marketTitle={section.title} sortKey="unrealizedPnl" config={sortConfig} onSort={setSortKey} />
                      <SortableHeader label={zh ? '已实现盈亏' : 'Realized P/L'} marketTitle={section.title} sortKey="realizedPnl" config={sortConfig} onSort={setSortKey} />
                    </tr></thead>
                    <tbody>
                      {sortedPositions.map((position) => <tr key={`${position.accountId}-${position.code}-${position.positionSide}`} className="border-b border-border/40 last:border-0">
                        <td className="max-w-[240px] px-3 py-3">
                          <p className="text-base font-semibold text-foreground">{displayCode(position.code)}</p>
                          <p className="mt-0.5 truncate text-xs text-secondary-text" title={position.name}>{position.name || '—'}</p>
                          <a href={positionAnalysisHref(position)} className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary hover:text-primary/80">
                            <Sparkles className="h-3 w-3" aria-hidden="true" />
                            {zh ? 'AI 分析' : 'AI analysis'}
                          </a>
                        </td>
                        <td className={`px-3 py-3 text-right font-medium tabular-nums ${pnlTone(position.todayChangePct)}`}>{formatSignedPercent(position.todayChangePct, locale)}</td>
                        <td className="px-3 py-3 text-right text-foreground">{optionalNumber(position.quantity, locale, 4)}</td>
                        <td className="px-3 py-3 text-right text-foreground tabular-nums">{formatPositionMoney(position.costPrice, position.currency, locale)}</td>
                        <td className="px-3 py-3 text-right text-foreground tabular-nums">{formatPositionMoney(position.currentPrice, position.currency, locale)}</td>
                        <td className="px-3 py-3 text-right font-medium text-foreground tabular-nums">{formatPositionMoney(position.marketValue, position.currency, locale)}</td>
                        <td className="px-3 py-3 text-right text-secondary-text tabular-nums">{section.marketValue != null && section.marketValue > 0 && position.marketValue != null ? `${(position.marketValue / section.marketValue * 100).toFixed(1)}%` : '—'}</td>
                        <td className={`px-3 py-3 text-right font-medium tabular-nums ${pnlTone(position.todayPnl)}`}>{formatPositionMoney(position.todayPnl, position.currency, locale, true)}</td>
                        <td className={`px-3 py-3 text-right font-medium tabular-nums ${pnlTone(position.holdingPnl)}`}>{formatPositionMoney(position.holdingPnl, position.currency, locale, true)}</td>
                        <td className={`px-3 py-3 text-right font-medium tabular-nums ${pnlTone(position.unrealizedPnl)}`}>
                          <div className="flex items-start justify-end gap-1.5">
                            <span aria-hidden="true">{position.unrealizedPnl == null || Math.abs(position.unrealizedPnl) < 0.005 ? '—' : position.unrealizedPnl > 0 ? '↑' : '↓'}</span>
                            <span>
                              <span className="block">{formatPositionMoney(position.unrealizedPnl, position.currency, locale, true)}</span>
                              <span className="mt-0.5 block text-xs">{formatSignedPercent(position.unrealizedPnlPct, locale)}</span>
                            </span>
                          </div>
                        </td>
                        <td className={`px-3 py-3 text-right font-medium tabular-nums ${pnlTone(position.realizedPnl)}`}>{formatPositionMoney(position.realizedPnl, position.currency, locale, true)}</td>
                      </tr>)}
                    </tbody>
                  </table>
                  {section.positions.length === 0 ? <p className="py-10 text-center text-sm text-secondary-text">{zh ? `当前没有${section.key === 'us' ? '美股' : '港股'}持仓。` : `No ${section.key === 'us' ? 'US' : 'Hong Kong'} positions.`}</p> : null}
                </div>
              </SectionCard>
              );
            })}
          </>
        )}
      </div>
    </AppPage>
  );
};

export default AccountPage;
