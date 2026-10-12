import { useEffect, useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import {
  LayoutDashboard, Map, ListChecks, TriangleAlert, GitBranch, Waypoints,
  Rows3, Database, Settings, PanelLeftClose, PanelLeft, Search, Bell,
  LogOut, ChevronDown, Check, Moon, Sun, ChefHat, Share2, Waves, Users, Car
} from 'lucide-react';
import { motion } from 'framer-motion';
import { Button, Input, Badge } from '@/components/ui';
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuSeparator, DropdownMenuTrigger,
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue
} from '@/components/overlays';
import { useApp, ROLES } from '@/lib/store.jsx';
import { useTheme } from '@/lib/theme.jsx';
import { AREAS } from '@/data/geo.js';
import { SCENARIO } from '@/data/scenario.js';
import { SentinelMark } from '@/components/brand.jsx';
import { cn } from '@/lib/utils';

const GROUPS = [
  {
    label: 'Operate',
    items: [
      { to: '/overview', label: 'Overview', icon: LayoutDashboard },
      { href: 'https://yekyahai.vercel.app/', label: 'Dam Failure', icon: Waves, external: true },
      { to: '/operations', label: 'Live operations', icon: Map },
      { to: '/crowd', label: 'Crowd & vision', icon: Users },
      { to: '/traffic', label: 'Traffic & vehicles', icon: Car },
      { to: '/response', label: 'Response center', icon: ListChecks }
    ]
  },
  {
    label: 'Investigate',
    items: [
      { to: '/incidents', label: 'Incidents', icon: TriangleAlert },
      { to: '/incidents/INC-104/evidence', label: 'Evidence & causes', icon: GitBranch },
      { to: '/graph', label: 'Graph explorer', icon: Share2 },
      { to: '/incidents/INC-104/cascade', label: 'Cascade risk', icon: Waypoints },
      { to: '/kitchen', label: 'Agent floor', icon: ChefHat }
    ]
  },
  {
    label: 'Platform',
    items: [
      { to: '/events', label: 'Event explorer', icon: Rows3 },
      { to: '/sources', label: 'Data sources', icon: Database },
      { to: '/settings', label: 'Settings & audit', icon: Settings }
    ]
  }
];

// Routes that own the whole viewport. The map and the agent floor must not scroll inside
// the shell, so the shell drops its scroll container for them.
const FULL_BLEED = ['/operations', '/kitchen', '/app/kitchen'];

// Routes that keep only the side rail. The full-screen graph drops the top bar and the
// system banner so the graph surface is the only thing on screen.
const MINIMAL_CHROME = [...FULL_BLEED, '/graph'];

function isFullBleed(pathname) {
  return FULL_BLEED.includes(pathname) || /^\/(graph(\/[^/]+)?|incidents\/[^/]+\/graph)$/.test(pathname);
}

function isMinimalChrome(pathname) {
  return isFullBleed(pathname);
}

// Small, quiet status indicator rather than a loud badge. Operating mode is
// legitimate context, but it is not an alarm.
export function ModeIndicator() {
  const { sources, simulatedOutage } = useApp();
  const replay = sources.some(item => ['REPLAY', 'SYNTHETIC'].includes(item.mode));
  const live = sources.filter(item => item.mode === 'LIVE_API' && item.health === 'HEALTHY').length;
  const outage = simulatedOutage.length;

  const tone = outage ? 'text-critical' : live > 0 ? 'text-healthy' : 'text-fg-muted';
  const label = outage ? `${outage} source offline` : live > 0 ? `${live} live · ${replay ? 'rest replay' : 'synthetic'}` : SCENARIO.mode;

  return (
    <span className={cn('inline-flex items-center gap-1.5 text-[12.5px]', tone)} title={SCENARIO.disclaimer}>
      <span className={cn('size-1.5 rounded-full', outage ? 'bg-critical' : live > 0 ? 'bg-healthy' : 'bg-fg-subtle')} />
      {label}
    </span>
  );
}

// Only actionable items get a badge; navigation counts are noise.
function NavItem({ item, collapsed, actionable }) {
  const location = useLocation();
  if (item.external) {
    return (
      <a
        href={item.href}
        title={collapsed ? item.label : undefined}
        className="group relative flex h-8 items-center gap-2.5 rounded-[6px] px-2.5 text-[13px] text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg"
      >
        <item.icon className="size-4 shrink-0 text-fg-subtle" />
        {!collapsed && <span className="truncate">{item.label}</span>}
      </a>
    );
  }
  const active = location.pathname === item.to
    || (item.to !== '/incidents' && location.pathname.startsWith(`${item.to}/`))
    || (item.to === '/incidents' && /^\/incidents\/.+\/(evidence|cascade)$/.test(location.pathname));

  return (
    <NavLink
      to={item.to}
      title={collapsed ? item.label : undefined}
      className={cn(
        'group relative flex h-8 items-center gap-2.5 rounded-[6px] px-2.5 text-[13px] transition-colors',
        active ? 'bg-surface-2 font-medium text-fg' : 'text-fg-muted hover:bg-surface-2 hover:text-fg'
      )}
    >
      {active && <span className="absolute left-0 top-1/2 h-4 w-[2px] -translate-y-1/2 rounded-r bg-accent" />}
      <item.icon className={cn('size-4 shrink-0', active ? 'text-accent' : 'text-fg-subtle')} />
      {!collapsed && <span className="truncate">{item.label}</span>}
      {!collapsed && actionable > 0 && (
        <span className="ml-auto rounded-full bg-critical-soft px-1.5 text-[11px] font-medium text-critical tabular-nums">
          {actionable}
        </span>
      )}
    </NavLink>
  );
}

export default function Shell({ children }) {
  const { role, timeWindow, area, search, dispatch, health, incidents } = useApp();
  const { isDark, toggle } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [bannerDismissed, setBannerDismissed] = useState(false);
  const minimalChrome = isMinimalChrome(location.pathname);
  const fullBleed = isFullBleed(location.pathname);

  // Only sources that are actively breaking a view earn a banner.
  const degraded = health.degraded.length + health.stale.length + health.offline.length;

  return (
    <div className={cn('flex h-full', collapsed ? '' : '')}>
      <aside
        className={cn(
          'flex shrink-0 flex-col border-r border-border bg-surface transition-[width] duration-200',
          collapsed ? 'w-[60px]' : 'w-[232px]'
        )}
      >
        <div className={cn('flex h-14 items-center border-b border-border', collapsed ? 'justify-center px-2' : 'gap-2.5 px-4')}>
          <SentinelMark size={22} />
          {!collapsed && (
            <div className="min-w-0">
              <div className="truncate text-[13px] font-semibold leading-tight tracking-[-0.01em]">Urban Sentinel</div>
              <div className="truncate text-[11.5px] leading-tight text-fg-subtle">Incident fusion</div>
            </div>
          )}
        </div>

        <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Primary">
          {GROUPS.map(group => (
            <div key={group.label} className="mb-4 last:mb-0">
              {!collapsed && (
                <div className="mb-1 px-2.5 text-[11.5px] font-medium text-fg-subtle">{group.label}</div>
              )}
              <div className="flex flex-col gap-0.5">
                {group.items.map(item => (
                  <NavItem
                    key={item.to}
                    item={item}
                    collapsed={collapsed}
                    actionable={item.to === '/incidents' ? incidents.filter(i => ['CRITICAL', 'HIGH'].includes(i.severity)).length : 0}
                  />
                ))}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-border p-2">
          <div className="flex flex-col gap-0.5">
            <NavLink
              to="/login"
              title={collapsed ? role.label : undefined}
              className={cn(
                'flex h-8 items-center gap-2.5 rounded-[6px] px-2.5 text-[13px] text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg',
                collapsed && 'justify-center px-0'
              )}
            >
              <LogOut className="size-4 shrink-0 text-fg-subtle" />
              {!collapsed && <span className="truncate">{role.label}</span>}
            </NavLink>
            <button
              onClick={() => setCollapsed(value => !value)}
              title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
              aria-expanded={!collapsed}
              className={cn(
                'flex h-8 w-full items-center gap-2.5 rounded-[6px] px-2.5 text-[13px] text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg',
                collapsed && 'justify-center px-0'
              )}
            >
              {collapsed ? <PanelLeft className="size-4 shrink-0 text-fg-subtle" /> : <PanelLeftClose className="size-4 shrink-0 text-fg-subtle" />}
              {!collapsed && <span>Collapse</span>}
            </button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        {!minimalChrome && (
        <header className="flex h-14 shrink-0 items-center gap-3 border-b border-border px-5">
          <div className="flex items-center gap-1.5">
            <Select value={area} onValueChange={value => dispatch({ type: 'setArea', value })}>
              <SelectTrigger className="h-8 w-[150px] border-transparent bg-transparent hover:bg-surface-2" aria-label="Operating area">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="All areas">All areas</SelectItem>
                {AREAS.map(item => <SelectItem key={item.area_id} value={item.name}>{item.name}</SelectItem>)}
              </SelectContent>
            </Select>
            <Select value={timeWindow} onValueChange={value => dispatch({ type: 'setTimeWindow', value })}>
              <SelectTrigger className="h-8 w-[132px] border-transparent bg-transparent hover:bg-surface-2" aria-label="Time range">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {[['15m', 'Last 15 min'], ['60m', 'Last 60 min'], ['6h', 'Last 6 hours'], ['24h', 'Last 24 hours']].map(([value, label]) => (
                  <SelectItem key={value} value={value}>{label}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="relative ml-auto w-[260px]">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-fg-subtle" />
            <Input
              value={search}
              onChange={event => dispatch({ type: 'setSearch', value: event.target.value })}
              onKeyDown={event => { if (event.key === 'Enter') window.location.assign(`/events?q=${encodeURIComponent(search)}`); }}
              placeholder="Search events, incidents"
              aria-label="Global search"
              className="h-8 border-transparent bg-surface-2 pl-8 hover:border-border"
            />
          </div>

          <ModeIndicator />

          <button
            onClick={toggle}
            className="grid size-8 place-items-center rounded-[6px] text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg"
            aria-label={`Switch to ${isDark ? 'light' : 'dark'} theme`}
            title={`Switch to ${isDark ? 'light' : 'dark'} theme`}
          >
            {isDark ? <Sun className="size-4" /> : <Moon className="size-4" />}
          </button>

          <button className="relative grid size-8 place-items-center rounded-[6px] text-fg-muted transition-colors hover:bg-surface-2 hover:text-fg" aria-label="Notifications">
            <Bell className="size-4" />
            {degraded > 0 && <span className="absolute right-1.5 top-1.5 size-1.5 rounded-full bg-critical" />}
          </button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button className="flex h-8 items-center gap-1.5 rounded-[6px] px-1.5 transition-colors hover:bg-surface-2" aria-label="Account and role menu">
                <span className="grid size-6 place-items-center rounded-full bg-surface-3 text-[11px] font-semibold text-fg-muted">
                  {role.id.slice(0, 2)}
                </span>
                <ChevronDown className="size-3.5 text-fg-subtle" />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
              <div className="px-2 py-1.5 text-[12px] text-fg-subtle">Signed in as {role.label}</div>
              <DropdownMenuSeparator />
              {Object.values(ROLES).map(option => (
                <DropdownMenuItem key={option.id} onSelect={() => dispatch({ type: 'setRole', role: option.id })}>
                  <span className="flex-1">{option.label}</span>
                  {role.id === option.id && <Check className="size-3.5 text-accent" />}
                </DropdownMenuItem>
              ))}
            </DropdownMenuContent>
          </DropdownMenu>
        </header>
        )}

        {!minimalChrome && degraded > 0 && !bannerDismissed && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            className="flex shrink-0 items-center gap-2 border-b border-degraded/25 bg-degraded-soft px-5 py-2 text-[12.5px] text-degraded"
          >
            <span className="size-1.5 shrink-0 rounded-full bg-degraded" />
            <span>
              {health.offline.length > 0 && `${health.offline.length} offline · `}
              {health.stale.length > 0 && `${health.stale.length} stale · `}
              {health.degraded.length} degraded.{' '}
              <span className="text-fg-muted">Unaffected panels keep serving data. Missing signals are not evidence that conditions are safe.</span>
            </span>
            <div className="ml-auto flex items-center gap-1">
              <Button variant="ghost" size="sm" onClick={() => window.location.assign('/sources')}>Review</Button>
              <Button variant="ghost" size="sm" onClick={() => setBannerDismissed(true)}>Dismiss</Button>
            </div>
          </motion.div>
        )}

        <main className={cn(
          'min-h-0 flex-1',
          fullBleed ? 'overflow-hidden' : 'overflow-y-auto'
        )}>
          {children}
        </main>
      </div>
    </div>
  );
}

// Shared page frame so every route keeps the same header rhythm.
export function PageHeader({ title, description, actions }) {
  return (
    <div className="flex items-start gap-4 border-b border-border px-6 py-5">
      <div className="min-w-0">
        <h1 className="text-[24px] font-semibold leading-tight tracking-[-0.015em] text-fg">{title}</h1>
        {description && <p className="mt-1 max-w-[70ch] text-[13px] leading-snug text-fg-muted">{description}</p>}
      </div>
      {actions && <div className="ml-auto flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function PageBody({ className, children }) {
  return <div className={cn('px-6 py-5', className)}>{children}</div>;
}
