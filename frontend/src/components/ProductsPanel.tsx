import { formatMoney } from "../lib/format";
import type { Product } from "../types";

const LOW_STOCK = 5;

export function ProductsPanel({ products }: { products: Product[] }) {
  const sorted = [...products].sort((a, b) => a.stockQty - b.stockQty);
  const maxStock = Math.max(1, ...products.map((product) => product.stockQty));

  return (
    <section className="panel panel--products" aria-labelledby="products-heading">
      <header className="panel__header">
        <h2 id="products-heading">Inventory</h2>
        <span className="panel__meta">lowest stock first</span>
      </header>
      {sorted.length === 0 ? (
        <p className="feed__empty">No products.</p>
      ) : (
        <ul className="stock">
          {sorted.map((product) => {
            const low = product.stockQty <= LOW_STOCK;
            return (
              <li key={product.id} className={`stock__item${low ? " stock__item--low" : ""}`}>
                <div className="stock__row">
                  <span className="stock__name">{product.name}</span>
                  <span className="stock__qty">
                    {product.stockQty}
                    {low && <span className="stock__flag">low</span>}
                  </span>
                </div>
                <div className="stock__bar" aria-hidden="true">
                  <div
                    className="stock__fill"
                    style={{ width: `${(product.stockQty / maxStock) * 100}%` }}
                  />
                </div>
                <div className="stock__price">{formatMoney(product.price)}</div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
