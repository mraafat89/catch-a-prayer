/**
 * Feature tests for data source badge logic.
 * Rules: PRAYER_LOGIC_RULES.md §6
 */

export {};

const WEBSITE_SOURCES = new Set([
  'mosque_website_html', 'mosque_website_js', 'mosque_website',
  'static_html', 'playwright_html', 'vision_ai',
]);

interface MockPrayer {
  prayer?: string;
  adhan_source?: string | null;
  iqama_source?: string | null;
  data_freshness?: string | null;
}

function dataSourceBadge(prayers: MockPrayer[]): { label: string; color: string } {
  if (!prayers.length) return { label: '~ Estimated times — help us get real times', color: 'text-amber-600' };
  const relevant = prayers.filter(p => p.prayer !== 'fajr');
  const sample = relevant.length ? relevant[0] : prayers[0];
  const adhanSrc = sample.adhan_source ?? '';
  const iqamaSrc = sample.iqama_source ?? '';
  const freshness = sample.data_freshness ?? null;
  const freshSuffix = freshness ? ` · ${freshness}` : '';

  const adhanVerified = WEBSITE_SOURCES.has(adhanSrc);
  const iqamaVerified = WEBSITE_SOURCES.has(iqamaSrc);

  if (adhanVerified && iqamaVerified) return { label: `✓ From mosque website${freshSuffix}`, color: 'text-green-700' };
  if (adhanSrc === 'mawaqit_api' || iqamaSrc === 'mawaqit_api') return { label: `From Mawaqit${freshSuffix}`, color: 'text-green-700' };
  if (adhanSrc === 'islamicfinder' || iqamaSrc === 'islamicfinder') return { label: `From IslamicFinder${freshSuffix}`, color: 'text-gray-500' };
  if (adhanSrc === 'user_submitted' || iqamaSrc === 'user_submitted') return { label: `Community-submitted${freshSuffix}`, color: 'text-blue-600' };
  if (adhanVerified && !iqamaVerified) return { label: '~ Iqama estimated', color: 'text-amber-600' };
  return { label: '~ Estimated times — help us get real times', color: 'text-amber-600' };
}

describe('Data source badge', () => {
  test('mosque website → green verified', () => {
    const badge = dataSourceBadge([
      { adhan_source: 'mosque_website_html', iqama_source: 'mosque_website_html', data_freshness: '2 days ago' },
    ]);
    expect(badge.color).toBe('text-green-700');
    expect(badge.label).toContain('mosque website');
    expect(badge.label).toContain('2 days ago');
  });

  test('mawaqit → green', () => {
    const badge = dataSourceBadge([
      { adhan_source: 'mawaqit_api', iqama_source: 'mawaqit_api' },
    ]);
    expect(badge.color).toBe('text-green-700');
    expect(badge.label).toContain('Mawaqit');
  });

  test('islamicfinder → gray', () => {
    const badge = dataSourceBadge([
      { adhan_source: 'islamicfinder', iqama_source: 'islamicfinder' },
    ]);
    expect(badge.color).toBe('text-gray-500');
  });

  test('user_submitted → blue', () => {
    const badge = dataSourceBadge([
      { adhan_source: 'user_submitted', iqama_source: 'user_submitted' },
    ]);
    expect(badge.color).toBe('text-blue-600');
    expect(badge.label).toContain('Community');
  });

  test('calculated/estimated → amber with help prompt', () => {
    const badge = dataSourceBadge([
      { adhan_source: 'calculated', iqama_source: 'estimated' },
    ]);
    expect(badge.color).toBe('text-amber-600');
    expect(badge.label).toContain('help us get real times');
  });

  test('adhan scraped + iqama estimated → amber', () => {
    const badge = dataSourceBadge([
      { adhan_source: 'mosque_website_html', iqama_source: 'estimated' },
    ]);
    expect(badge.color).toBe('text-amber-600');
    expect(badge.label).toContain('Iqama estimated');
  });

  test('empty prayers → amber estimated', () => {
    const badge = dataSourceBadge([]);
    expect(badge.color).toBe('text-amber-600');
  });

  test('uses non-fajr prayer for source check', () => {
    // Fajr may have different source than others — badge should use Dhuhr
    const badge = dataSourceBadge([
      { prayer: 'fajr', adhan_source: 'calculated', iqama_source: 'estimated' },
      { prayer: 'dhuhr', adhan_source: 'mosque_website_html', iqama_source: 'mosque_website_html' },
    ]);
    expect(badge.color).toBe('text-green-700');
  });
});
