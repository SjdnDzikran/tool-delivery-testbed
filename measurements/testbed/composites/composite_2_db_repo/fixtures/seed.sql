-- Seed data for composite_2_db_repo [ours].
--
-- 30 deterministic rows: 6 products x 5 rows over 3 regions.
-- Per product the region pattern is fixed: north, south, west, north, south
-- (2 north rows, 2 south rows, 1 west row), so every aggregate below is exact.
--
-- Design properties (rig-side; the agent must compute these from the DB):
--   * Winner by total units is unambiguous: Aurora Lamp 620 vs runner-up
--     Birch Desk 590 (gap 30). No ties anywhere.
--   * A per-region aggregation alone picks the WRONG product in every
--     region: north -> Birch Desk (300), south -> Birch Desk (195),
--     west -> Cedar Chair (170). Only the full cross-region total works.
--   * Ranking by revenue instead of units picks a different product
--     altogether (Damask Rug, 130000.00 - which is LAST by units), catching
--     wrong-column errors.
--
-- Aggregates for review:
--   product       units N/S/W       total   unit price   revenue total
--   Aurora Lamp   290/180/150        620       85.00       52700.00  <- units winner
--   Birch Desk    300/195/ 95        590      180.00      106200.00  <- units runner-up
--   Cedar Chair   175/185/170        530       95.00       50350.00
--   Fig Tree      185/165/ 80        430       42.00       18060.00
--   Enameled Mug  155/140/ 65        360       14.50        5220.00
--   Damask Rug    110/ 95/ 45        250      520.00      130000.00  <- revenue winner
INSERT INTO public.product_sales (product, region, units, revenue) VALUES
    ('Aurora Lamp',  'north', 150, 12750.00),
    ('Aurora Lamp',  'south', 130, 11050.00),
    ('Aurora Lamp',  'west',  150, 12750.00),
    ('Aurora Lamp',  'north', 140, 11900.00),
    ('Aurora Lamp',  'south',  50,  4250.00),
    ('Birch Desk',   'north', 160, 28800.00),
    ('Birch Desk',   'south', 100, 18000.00),
    ('Birch Desk',   'west',   95, 17100.00),
    ('Birch Desk',   'north', 140, 25200.00),
    ('Birch Desk',   'south',  95, 17100.00),
    ('Cedar Chair',  'north',  90,  8550.00),
    ('Cedar Chair',  'south',  95,  9025.00),
    ('Cedar Chair',  'west',  170, 16150.00),
    ('Cedar Chair',  'north',  85,  8075.00),
    ('Cedar Chair',  'south',  90,  8550.00),
    ('Damask Rug',   'north',  55, 28600.00),
    ('Damask Rug',   'south',  50, 26000.00),
    ('Damask Rug',   'west',   45, 23400.00),
    ('Damask Rug',   'north',  55, 28600.00),
    ('Damask Rug',   'south',  45, 23400.00),
    ('Enameled Mug', 'north',  80,  1160.00),
    ('Enameled Mug', 'south',  70,  1015.00),
    ('Enameled Mug', 'west',   65,   942.50),
    ('Enameled Mug', 'north',  75,  1087.50),
    ('Enameled Mug', 'south',  70,  1015.00),
    ('Fig Tree',     'north',  95,  3990.00),
    ('Fig Tree',     'south',  85,  3570.00),
    ('Fig Tree',     'west',   80,  3360.00),
    ('Fig Tree',     'north',  90,  3780.00),
    ('Fig Tree',     'south',  80,  3360.00);
