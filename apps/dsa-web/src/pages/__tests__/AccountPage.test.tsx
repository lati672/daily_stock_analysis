import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../contexts/UiLanguageContext';
import AccountPage from '../AccountPage';

const { get, post, put } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn() }));

vi.mock('../../api/index', () => ({ default: { get, post, put } }));

function renderPage() {
  return render(<UiLanguageProvider><AccountPage /></UiLanguageProvider>);
}

function appearsBefore(left: Element, right: Element): boolean {
  return Boolean(left.compareDocumentPosition(right) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe('AccountPage', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.localStorage.setItem('dsa.uiLanguage', 'zh');
    post.mockReset();
    get.mockReset();
    put.mockReset();
    get.mockResolvedValue({ data: {
      enabled: false,
      us_market_open_today: true,
      schedule_time: '18:10',
      next_run_at: null,
      running: false,
      last_run_at: null,
      last_success_at: null,
      last_error: null,
    } });
    put.mockResolvedValue({ data: {
      enabled: true,
      us_market_open_today: true,
      schedule_time: '18:10',
      next_run_at: '2026-09-04T18:10:00',
      running: false,
      last_run_at: null,
      last_success_at: null,
      last_error: null,
    } });
  });

  it('persists the automatic portfolio digest switch', async () => {
    post.mockResolvedValue({ data: {
      connected: true,
      provider: 'moomoo',
      host: '127.0.0.1',
      port: 11111,
      read_only: true,
      currency: 'USD',
      accounts: [],
      positions: [],
    } });

    renderPage();
    const toggle = await screen.findByRole('switch', { name: '自动持仓日报' });
    expect(toggle).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(toggle);

    await waitFor(() => expect(put).toHaveBeenCalledWith(
      '/api/v1/portfolio/brokers/moomoo/daily-report/settings',
      { enabled: true },
    ));
    expect(toggle).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByText(/每天 18:10/)).toBeInTheDocument();
  });

  it('shows the automatic digest as paused on a US market holiday', async () => {
    get.mockResolvedValueOnce({ data: {
      enabled: true,
      us_market_open_today: false,
      schedule_time: '18:10',
      next_run_at: '2026-09-08T18:10:00',
      running: false,
      last_run_at: null,
      last_success_at: null,
      last_error: null,
    } });
    post.mockResolvedValue({ data: {
      connected: true,
      provider: 'moomoo',
      host: '127.0.0.1',
      port: 11111,
      read_only: true,
      currency: 'USD',
      accounts: [],
      positions: [],
    } });

    renderPage();
    expect(await screen.findByText('今日暂停 · 美股休市')).toBeInTheDocument();
    expect(screen.getByText(/下次 2026\/09\/08 18:10/)).toBeInTheDocument();
  });

  it('connects to the backend and renders Moomoo positions', async () => {
    post.mockResolvedValue({ data: {
      connected: true,
      provider: 'moomoo',
      host: '127.0.0.1',
      port: 11111,
      read_only: true,
      currency: 'USD',
      total_market_value: 13900,
      holding_pnl: 1095,
      holding_pnl_pct: 8.55,
      total_pnl: 1095,
      total_pnl_pct: 8.55,
      today_pnl: 138,
      today_pnl_pct: 1.0,
      accounts: [{ account_id: 1001, role: 'NORMAL', security_firm: 'FUTUSECURITIES', position_count: 2, currency: 'USD', market_value: 13900, holding_pnl: 1095, holding_pnl_pct: 8.55, total_pnl: 1095, total_pnl_pct: 8.55, today_pnl: 138, today_pnl_pct: 1.0 }],
      cash_balances: [
        { account_id: 1001, currency: 'AUD', cash: 3.57, available_for_withdrawal: 3.57, net_cash_power: 3.57 },
        { account_id: 1001, currency: 'USD', cash: 2790.37, available_for_withdrawal: 1383.57, net_cash_power: 2790.37 },
        { account_id: 1001, currency: 'HKD', cash: 720.36, available_for_withdrawal: 720.36, net_cash_power: 720.36 },
      ],
      positions: [
        { account_id: 1001, code: 'US.AAPL', name: 'Apple Incorporated', position_side: 'LONG', quantity: 10, cost_price: 180.5, current_price: 190, market_value: 1900, holding_pnl: 95, holding_pnl_pct: 5.25, unrealized_pnl: 70, unrealized_pnl_pct: 3.83, realized_pnl: 25, today_pnl: 38, today_change_pct: 1.25, currency: 'USD' },
        { account_id: 1001, code: 'HK.00700', name: '腾讯控股', position_side: 'LONG', quantity: 20, cost_price: 550, current_price: 600, market_value: 12000, holding_pnl: 1000, holding_pnl_pct: 9.09, unrealized_pnl: 900, unrealized_pnl_pct: 8.11, realized_pnl: 100, today_pnl: 100, today_change_pct: -0.75, currency: 'HKD', exchange_rate_to_reporting_currency: 0.128 },
      ],
    } });

    renderPage();
    await waitFor(() => expect(post).toHaveBeenCalledWith('/api/v1/portfolio/brokers/moomoo/connect'));
    expect(await screen.findByText('Apple Incorporated')).toBeInTheDocument();
    expect(screen.getByText('已连接 · 只读')).toBeInTheDocument();
    expect(screen.getByText('美股持仓')).toBeInTheDocument();
    expect(screen.getByText('港股持仓')).toBeInTheDocument();
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('00700')).toBeInTheDocument();
    expect(screen.queryByText('LONG')).not.toBeInTheDocument();
    expect(screen.queryByText(/#1001/)).not.toBeInTheDocument();
    expect(screen.getAllByText('总市值')).toHaveLength(3);
    expect(screen.getByText('$13,900.00')).toBeInTheDocument();
    expect(screen.getByText('分币种现金')).toBeInTheDocument();
    expect(screen.getAllByText(/AUD\s*3\.57/)).toHaveLength(3);
    expect(screen.getAllByText(/USD\s*2,790\.37/)).toHaveLength(2);
    expect(screen.getByText(/USD\s*1,383\.57/)).toBeInTheDocument();
    expect(screen.getAllByText(/HKD\s720\.36/)).toHaveLength(3);
    expect(screen.getAllByText('持仓盈亏')).toHaveLength(5);
    expect(screen.queryByText('总盈亏')).not.toBeInTheDocument();
    expect(screen.getAllByText('平均成本')).toHaveLength(2);
    expect(screen.getAllByText('今日盈亏')).toHaveLength(5);
    expect(screen.getAllByText('今日涨幅')).toHaveLength(2);
    expect(screen.getByText('+1.25%')).toHaveClass('text-success');
    expect(screen.getByText('-0.75%')).toHaveClass('text-danger');
    expect(screen.getAllByText('已实现盈亏')).toHaveLength(2);
    expect(screen.getAllByText('仓位')).toHaveLength(2);
    expect(screen.getAllByText('100.0%')).toHaveLength(2);
    expect(screen.getAllByText('$1,900.00')).toHaveLength(2);
    expect(screen.getAllByText(/HKD\s12,000\.00/)).toHaveLength(1);
    expect(screen.getByText('12,000.00')).toBeInTheDocument();
    expect(screen.getAllByText('+$95.00')).toHaveLength(2);
    expect(screen.getAllByText(/\+HKD\s1,000\.00/)).toHaveLength(1);
    expect(screen.getByText('+1,000.00')).toBeInTheDocument();
    expect(screen.getAllByText('+$38.00')).toHaveLength(2);
    expect(screen.getAllByText(/\+HKD\s100\.00/)).toHaveLength(1);
    expect(screen.getAllByText('+100.00')).toHaveLength(2);
    expect(screen.queryByText('可用')).not.toBeInTheDocument();
    expect(screen.getByText('+$70.00')).toBeInTheDocument();
    expect(screen.getByText('+3.83%')).toBeInTheDocument();
    expect(screen.getByText('+$25.00')).toBeInTheDocument();
    const currencySwitch = screen.getByRole('switch', { name: '港股金额换算为美元' });
    expect(currencySwitch).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(currencySwitch);
    expect(currencySwitch).toHaveAttribute('aria-checked', 'true');
    expect(window.localStorage.getItem('dsa.account.hkDisplayCurrency')).toBe('USD');
    expect(screen.getAllByText('$1,536.00')).toHaveLength(2);
    expect(screen.getByText('$70.40')).toBeInTheDocument();
    expect(screen.getByText('$76.80')).toBeInTheDocument();
    expect(screen.getAllByText('+$128.00')).toHaveLength(2);
    expect(screen.getByText('+$115.20')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'AI 归因' })).toHaveAttribute('href', '/chat?moomoo=portfolio&task=today-attribution&new=1');
    expect(screen.getAllByRole('link', { name: 'AI 分析' })[0]).toHaveAttribute('href', expect.stringMatching(/stock=AAPL.*new=1/));
    expect(screen.getAllByRole('link', { name: 'AI 分析' })[1]).toHaveAttribute('href', expect.stringMatching(/stock=HK00700.*new=1/));

    fireEvent.click(screen.getByRole('button', { name: '刷新持仓' }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(2));
  });

  it('sorts each market by day change by default and restores it on the third click', async () => {
    post.mockResolvedValue({ data: {
      connected: true,
      provider: 'moomoo',
      host: '127.0.0.1',
      port: 11111,
      read_only: true,
      currency: 'USD',
      total_market_value: 300,
      accounts: [{ account_id: 1001, role: 'NORMAL', security_firm: 'FUTUSECURITIES', position_count: 3, currency: 'USD', market_value: 300 }],
      positions: [
        { account_id: 1001, code: 'US.LOSS', name: 'Loss', position_side: 'LONG', quantity: 1, market_value: 100, today_pnl: -5, today_change_pct: 2, currency: 'USD' },
        { account_id: 1001, code: 'US.NODATA', name: 'No data', position_side: 'LONG', quantity: 1, market_value: 100, today_pnl: null, today_change_pct: null, currency: 'USD' },
        { account_id: 1001, code: 'US.GAIN', name: 'Gain', position_side: 'LONG', quantity: 1, market_value: 100, today_pnl: 10, today_change_pct: -1, currency: 'USD' },
      ],
    } });

    renderPage();
    const gain = await screen.findByText('GAIN');
    const loss = screen.getByText('LOSS');
    const noData = screen.getByText('NODATA');
    expect(appearsBefore(loss, gain)).toBe(true);
    expect(appearsBefore(gain, noData)).toBe(true);
    expect(screen.getByRole('button', { name: '美股持仓：今日涨幅，降序' }).closest('th')).toHaveAttribute('aria-sort', 'descending');

    fireEvent.click(screen.getByRole('button', { name: '美股持仓：证券，未排序' }));
    expect(appearsBefore(noData, loss)).toBe(true);
    expect(appearsBefore(loss, gain)).toBe(true);
    expect(screen.getByRole('button', { name: '美股持仓：证券，降序' }).closest('th')).toHaveAttribute('aria-sort', 'descending');

    fireEvent.click(screen.getByRole('button', { name: '美股持仓：证券，降序' }));
    expect(appearsBefore(gain, loss)).toBe(true);
    expect(appearsBefore(loss, noData)).toBe(true);

    fireEvent.click(screen.getByRole('button', { name: '美股持仓：证券，升序' }));
    expect(screen.getByRole('button', { name: '美股持仓：证券，未排序' }).closest('th')).toHaveAttribute('aria-sort', 'none');
    expect(screen.getByRole('button', { name: '美股持仓：今日涨幅，降序' }).closest('th')).toHaveAttribute('aria-sort', 'descending');
    expect(appearsBefore(loss, gain)).toBe(true);
    expect(appearsBefore(gain, noData)).toBe(true);
  });
});
