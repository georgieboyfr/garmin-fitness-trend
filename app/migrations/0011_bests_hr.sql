-- FC moyenne de chaque meilleur effort (distances et montées), et paliers de montée :
--   climb : key = 0 (meilleure montée de plus de 200 m, extra = son D+) ou key = palier de D+
--           (100, 200, 500, 1000 m), value = VAM (m/h) sur le palier le plus rapide, extra = palier
ALTER TABLE activity_bests ADD COLUMN avg_hr REAL;
