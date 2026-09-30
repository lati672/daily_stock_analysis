import { useCallback, useEffect, useMemo, useState } from 'react';
import axios from 'axios';
import { BellRing, ChevronDown, ChevronUp, Clock3, Link2, RefreshCw, Send, ShieldCheck, Sparkles, Unplug } from 'lucide-react';
import { moomooApi } from '../api/moomoo';
import { AppPage, Card, InlineAlert, PageHeader, SectionCard } from '../components/common';
import { useUiLanguage } from '../contexts/UiLanguageContext';
import type { MoomooDailyReportStatus, MoomooSnapshot } from '../types/moomoo';

type MarketKey = 'us' | 'hk' | 'other';
type SortKey = 'code' | 'todayChangePct' | 'quantity' | 'costPrice' | 'currentPrice' | 'marketValue' | 'weight' | 'todayPnl' | 'holdingPnl' | 'unrealizedPnl' | 'realizedPnl';
type SortDirection = 'desc' | 'asc';
type SortConfig = { key: SortKey; direction: SortDirection };
const DEFAULT_MARKET_SORT: SortConfig = { key: 'todayChangePct', direction: 'desc' };
const HK_DISPLAY_CURRENCY_KEY = 'dsa.account.hkDisplayCurrency';

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

function formatCashMoney(value: number | null | undefined, currency: string, locale: string): string {
  if (value == null) return '—';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currency || 'USD',
    currencyDisplay: 'code',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
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

function convertedPositionValue(
  value: number | null | undefined,
  position: MoomooSnapshot['positions'][number],
  convertToUsd: boolean,
): number | null {
  if (value == null) return null;
  if (!convertToUsd || position.currency.toUpperCase() === 'USD') return value;
  const rate = position.exchangeRateToReportingCurrency;
  return rate != null && Number.isFinite(rate) && rate > 0 ? value * rate : null;
}

function sumConvertedPositionField(
  positions: MoomooSnapshot['positions'],
  select: (position: MoomooSnapshot['positions'][number]) => number | null | undefined,
): number | null {
  const values = positions.map((position) => convertedPositionValue(select(position), position, true));
  return values.some((value) => value == null)
    ? null
    : values.reduce<number>((total, value) => total + (value ?? 0), 0);
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

function formatServerLocalDateTime(value: string, locale: string): string {
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) return value;
  const [, year, month, day, hour, minute] = match;
  return locale.startsWith('zh')
    ? `${year}/${month}/${day} ${hour}:${minute}`
    : `${year}-${month}-${day} ${hour}:${minute}`;
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
  const [dailyReport, setDailyReport] = useState<MoomooDailyReportStatus | null>(null);
  const [dailyReportSaving, setDailyReportSaving] = useState(false);
  const [dailyReportError, setDailyReportError] = useState<string | null>(null);
  const [showHongKongInUsd, setShowHongKongInUsd] = useState(() => (
    typeof window !== 'undefined' && window.localStorage.getItem(HK_DISPLAY_CURRENCY_KEY) === 'USD'
  ));
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

  const cashBalances = useMemo(() => {
    const selected = (snapshot?.cashBalances ?? []).filter((balance) => (
      accountId === 'all' || balance.accountId === accountId
    ));
    const aggregated = new Map<string, { cash: number; available: number | null; power: number | null }>();
    selected.forEach((balance) => {
      const currency = balance.currency.toUpperCase();
      const current = aggregated.get(currency) ?? { cash: 0, available: 0, power: 0 };
      current.cash += balance.cash;
      current.available = current.available == null || balance.availableForWithdrawal == null
        ? null
        : current.available + balance.availableForWithdrawal;
      current.power = current.power == null || balance.netCashPower == null
        ? null
        : current.power + balance.netCashPower;
      aggregated.set(currency, current);
    });
    const order = ['AUD', 'USD', 'HKD'];
    return [...aggregated.entries()]
      .sort(([left], [right]) => order.indexOf(left) - order.indexOf(right))
      .map(([currency, values]) => ({ currency, ...values }));
  }, [accountId, snapshot]);

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

  const loadDailyReportStatus = useCallback(async () => {
    try {
      setDailyReport(await moomooApi.getDailyReportStatus());
      setDailyReportError(null);
    } catch (err) {
      setDailyReportError(errorMessage(err, zh ? '无法读取持仓日报状态' : 'Unable to load daily report status'));
    }
  }, [zh]);

  const toggleDailyReport = useCallback(async () => {
    if (!dailyReport || dailyReportSaving) return;
    setDailyReportSaving(true);
    setDailyReportError(null);
    try {
      setDailyReport(await moomooApi.updateDailyReportSettings(!dailyReport.enabled));
    } catch (err) {
      setDailyReportError(errorMessage(err, zh ? '无法保存持仓日报开关' : 'Unable to save daily report setting'));
    } finally {
      setDailyReportSaving(false);
    }
  }, [dailyReport, dailyReportSaving, zh]);

  const runDailyReportNow = useCallback(async () => {
    if (dailyReportSaving) return;
    setDailyReportSaving(true);
    setDailyReportError(null);
    try {
      const result = await moomooApi.runDailyReportNow();
      setDailyReport((current) => current ? { ...current, running: result.running } : current);
    } catch (err) {
      setDailyReportError(errorMessage(err, zh ? '无法生成持仓日报' : 'Unable to generate daily report'));
    } finally {
      setDailyReportSaving(false);
    }
  }, [dailyReportSaving, zh]);

  useEffect(() => {
    void connect();
    void loadDailyReportStatus();
  }, [connect, loadDailyReportStatus]);

  useEffect(() => {
    if (!dailyReport?.running) return undefined;
    const timer = window.setInterval(() => void loadDailyReportStatus(), 5000);
    return () => window.clearInterval(timer);
  }, [dailyReport?.running, loadDailyReportStatus]);

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

        <SectionCard
          title={zh ? '自动持仓日报' : 'Automatic portfolio digest'}
          subtitle={zh ? '收盘后分析盈亏归因、主要新闻、集中度和明日关注点，并仅发送到 Discord。' : 'After close, analyze P/L attribution, material news, concentration and next-session watch points, then send only to Discord.'}
        >
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div className="flex min-w-0 items-start gap-3">
              <div className="mt-0.5 rounded-xl bg-primary/10 p-2 text-primary"><BellRing className="h-4 w-4" /></div>
              <div>
                <p className="text-sm font-medium text-foreground">
                  {dailyReport?.enabled
                    ? dailyReport.usMarketOpenToday === false
                      ? (zh ? '今日暂停 · 美股休市' : 'Paused today · US market closed')
                      : (zh ? '已开启' : 'Enabled')
                    : (zh ? '未开启' : 'Disabled')}
                </p>
                <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-secondary-text">
                  <Clock3 className="h-3.5 w-3.5" />
                  {zh ? `每天 ${dailyReport?.scheduleTime ?? '18:10'}（服务器本地时间）` : `Daily at ${dailyReport?.scheduleTime ?? '18:10'} (server local time)`}
                  {dailyReport?.nextRunAt ? <span>· {zh ? '下次 ' : 'Next '}{formatServerLocalDateTime(dailyReport.nextRunAt, locale)}</span> : null}
                </p>
                {dailyReport?.lastSuccessAt ? <p className="mt-1 text-xs text-secondary-text">{zh ? '最近成功：' : 'Last success: '}{formatServerLocalDateTime(dailyReport.lastSuccessAt, locale)}</p> : null}
              </div>
            </div>
            <div className="flex items-center gap-3">
              <button
                type="button"
                className="btn-secondary inline-flex items-center gap-2"
                disabled={!dailyReport || dailyReportSaving || dailyReport.running}
                onClick={() => void runDailyReportNow()}
              >
                {dailyReport?.running ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                {dailyReport?.running ? (zh ? '生成中…' : 'Generating…') : (zh ? '立即生成并发送' : 'Generate and send now')}
              </button>
              <button
                type="button"
                role="switch"
                aria-checked={dailyReport?.enabled ?? false}
                aria-label={zh ? '自动持仓日报' : 'Automatic portfolio digest'}
                disabled={!dailyReport || dailyReportSaving}
                onClick={() => void toggleDailyReport()}
                className={`relative h-7 w-12 rounded-full transition-colors ${dailyReport?.enabled ? 'bg-primary' : 'bg-border'} disabled:opacity-50`}
              >
                <span className={`absolute left-1 top-1 h-5 w-5 rounded-full bg-white shadow transition-transform ${dailyReport?.enabled ? 'translate-x-5' : 'translate-x-0'}`} />
              </button>
            </div>
          </div>
          {dailyReportError ? <div className="mt-4"><InlineAlert variant="danger" title={zh ? '持仓日报不可用' : 'Portfolio digest unavailable'} message={dailyReportError} /></div> : null}
          {dailyReport?.lastError ? <div className="mt-4"><InlineAlert variant="warning" title={zh ? '上次生成失败' : 'Last generation failed'} message={dailyReport.lastError} /></div> : null}
        </SectionCard>

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
              {cashBalances.length > 0 ? (
                <div className="mt-5 border-t border-border/50 pt-5">
                  <p className="text-xs font-medium text-secondary-text">{zh ? '分币种现金' : 'Cash by currency'}</p>
                  <div className="mt-3 grid gap-3 sm:grid-cols-3">
                    {cashBalances.map((balance) => (
                      <div key={balance.currency} className="rounded-lg border border-border/50 bg-surface/40 px-4 py-3">
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="text-xs font-semibold text-secondary-text">{balance.currency}</span>
                          <span className="text-lg font-semibold tabular-nums text-foreground">
                            {formatCashMoney(balance.cash, balance.currency, locale)}
                          </span>
                        </div>
                        <div className="mt-2 flex justify-between gap-3 text-xs text-muted-text">
                          <span>{zh ? '可提' : 'Withdrawable'}</span>
                          <span className="tabular-nums">{formatCashMoney(balance.available, balance.currency, locale)}</span>
                        </div>
                        <div className="mt-1 flex justify-between gap-3 text-xs text-muted-text">
                          <span>{zh ? '现金购买力' : 'Cash buying power'}</span>
                          <span className="tabular-nums">{formatCashMoney(balance.power, balance.currency, locale)}</span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ) : null}
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
              const canConvertHongKongToUsd = section.key === 'hk'
                && section.positions.length > 0
                && section.positions.every((position) => (
                  position.currency.toUpperCase() === 'USD'
                  || (position.exchangeRateToReportingCurrency != null
                    && Number.isFinite(position.exchangeRateToReportingCurrency)
                    && position.exchangeRateToReportingCurrency > 0)
                ));
              const convertHongKongToUsd = showHongKongInUsd && canConvertHongKongToUsd;
              const displayCurrency = convertHongKongToUsd ? 'USD' : section.currency;
              const displayMarketValue = convertHongKongToUsd
                ? sumConvertedPositionField(section.positions, (position) => position.marketValue)
                : section.marketValue;
              const displayHoldingPnl = convertHongKongToUsd
                ? sumConvertedPositionField(section.positions, (position) => position.holdingPnl)
                : section.holdingPnl;
              const displayTodayPnl = convertHongKongToUsd
                ? sumConvertedPositionField(section.positions, (position) => position.todayPnl)
                : section.todayPnl;
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
                actions={section.key === 'hk' ? (
                  <div className="flex items-center gap-2 text-xs text-secondary-text">
                    <span>{zh ? '显示币种' : 'Display currency'}</span>
                    <span className={!convertHongKongToUsd ? 'font-semibold text-foreground' : ''}>HKD</span>
                    <button
                      type="button"
                      role="switch"
                      aria-checked={convertHongKongToUsd}
                      aria-label={zh ? '港股金额换算为美元' : 'Convert Hong Kong amounts to USD'}
                      title={!canConvertHongKongToUsd
                        ? (zh ? '当前快照没有可用的港币兑美元汇率' : 'No HKD to USD rate is available for this snapshot')
                        : undefined}
                      disabled={!canConvertHongKongToUsd}
                      onClick={() => setShowHongKongInUsd((current) => {
                        const next = !current;
                        window.localStorage.setItem(HK_DISPLAY_CURRENCY_KEY, next ? 'USD' : 'HKD');
                        return next;
                      })}
                      className={`relative h-6 w-11 rounded-full transition-colors ${convertHongKongToUsd ? 'bg-primary' : 'bg-border'} disabled:cursor-not-allowed disabled:opacity-50`}
                    >
                      <span className={`absolute left-1 top-1 h-4 w-4 rounded-full bg-white shadow transition-transform ${convertHongKongToUsd ? 'translate-x-5' : ''}`} />
                    </button>
                    <span className={convertHongKongToUsd ? 'font-semibold text-foreground' : ''}>USD</span>
                  </div>
                ) : undefined}
              >
                <div className="mb-4 grid gap-4 border-y border-border/50 py-3 sm:grid-cols-3 sm:gap-6">
                  <div>
                    <p className="text-xs font-medium text-secondary-text">{zh ? '总市值' : 'Total market value'}</p>
                    <p className="mt-1 text-lg font-semibold text-foreground tabular-nums">
                      {formatMoney(displayMarketValue, displayCurrency, locale)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-secondary-text">{zh ? '持仓盈亏' : 'Position P/L'}</p>
                    <p className={`mt-1 text-lg font-semibold tabular-nums ${pnlTone(displayHoldingPnl)}`}>
                      {formatMoney(displayHoldingPnl, displayCurrency, locale, true)}
                    </p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-secondary-text">{zh ? '今日盈亏' : "Today's P/L"}</p>
                    <p className={`mt-1 text-lg font-semibold tabular-nums ${pnlTone(displayTodayPnl)}`}>
                      {formatMoney(displayTodayPnl, displayCurrency, locale, true)}
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
                      {sortedPositions.map((position) => {
                        const displayPositionCurrency = convertHongKongToUsd ? 'USD' : position.currency;
                        const displayPositionValue = (value: number | null | undefined) => (
                          convertedPositionValue(value, position, convertHongKongToUsd)
                        );
                        return <tr key={`${position.accountId}-${position.code}-${position.positionSide}`} className="border-b border-border/40 last:border-0">
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
                        <td className="px-3 py-3 text-right text-foreground tabular-nums">{formatPositionMoney(displayPositionValue(position.costPrice), displayPositionCurrency, locale)}</td>
                        <td className="px-3 py-3 text-right text-foreground tabular-nums">{formatPositionMoney(displayPositionValue(position.currentPrice), displayPositionCurrency, locale)}</td>
                        <td className="px-3 py-3 text-right font-medium text-foreground tabular-nums">{formatPositionMoney(displayPositionValue(position.marketValue), displayPositionCurrency, locale)}</td>
                        <td className="px-3 py-3 text-right text-secondary-text tabular-nums">{section.marketValue != null && section.marketValue > 0 && position.marketValue != null ? `${(position.marketValue / section.marketValue * 100).toFixed(1)}%` : '—'}</td>
                        <td className={`px-3 py-3 text-right font-medium tabular-nums ${pnlTone(position.todayPnl)}`}>{formatPositionMoney(displayPositionValue(position.todayPnl), displayPositionCurrency, locale, true)}</td>
                        <td className={`px-3 py-3 text-right font-medium tabular-nums ${pnlTone(position.holdingPnl)}`}>{formatPositionMoney(displayPositionValue(position.holdingPnl), displayPositionCurrency, locale, true)}</td>
                        <td className={`px-3 py-3 text-right font-medium tabular-nums ${pnlTone(position.unrealizedPnl)}`}>
                          <div className="flex items-start justify-end gap-1.5">
                            <span aria-hidden="true">{position.unrealizedPnl == null || Math.abs(position.unrealizedPnl) < 0.005 ? '—' : position.unrealizedPnl > 0 ? '↑' : '↓'}</span>
                            <span>
                              <span className="block">{formatPositionMoney(displayPositionValue(position.unrealizedPnl), displayPositionCurrency, locale, true)}</span>
                              <span className="mt-0.5 block text-xs">{formatSignedPercent(position.unrealizedPnlPct, locale)}</span>
                            </span>
                          </div>
                        </td>
                        <td className={`px-3 py-3 text-right font-medium tabular-nums ${pnlTone(position.realizedPnl)}`}>{formatPositionMoney(displayPositionValue(position.realizedPnl), displayPositionCurrency, locale, true)}</td>
                      </tr>;
                      })}
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
