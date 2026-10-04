import { useEffect, useRef, useState, type FormEvent } from "react";

import { useSessionContext } from "../app/session";
import { createOrder, fetchProducts } from "../lib/api";
import { formatMoney } from "../lib/format";
import type { OrderRecord, Product } from "../types";

interface Props {
  open: boolean;
  onClose: () => void;
  onPlaced: (order: OrderRecord) => void;
}

/** Places a real order through the gateway, to watch a saga run end to end. */
export function TestOrderDialog({ open, onClose, onPlaced }: Props) {
  const { api } = useSessionContext();
  const ref = useRef<HTMLDialogElement>(null);
  const [products, setProducts] = useState<Product[] | null>(null);
  const [productId, setProductId] = useState("");
  const [qty, setQty] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setError(null);
    api
      .withToken((token) => fetchProducts(token))
      .then((items) => {
        if (!active) return;
        setProducts(items);
        setProductId((current) => current || (items.find((item) => item.available > 0)?.id ?? ""));
      })
      .catch((caught: unknown) => {
        if (active) setError(caught instanceof Error ? caught.message : "Couldn't load products");
      });
    return () => {
      active = false;
    };
  }, [open, api]);

  const product = products?.find((item) => item.id === productId);

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!product) return;
    setSubmitting(true);
    setError(null);
    try {
      const order = await api.withToken((token) => createOrder(token, [{ productId: product.id, qty }]));
      onPlaced(order);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Couldn't place the order");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <dialog
      ref={ref}
      className="dialog"
      aria-labelledby="test-order-title"
      onCancel={(event) => {
        event.preventDefault();
        if (!submitting) onClose();
      }}
    >
      <form className="dialog__body" onSubmit={submit}>
        <h2 id="test-order-title" className="dialog__title">
          Place a test order
        </h2>
        <p className="dialog__content">
          Creates a real order as this admin account. It runs through the full saga: stock
          reservation, payment, commit and fulfilment. Ordering more than is available exercises
          the cancellation path.
        </p>
        <label className="field">
          <span>Product</span>
          <select
            value={productId}
            onChange={(event) => setProductId(event.target.value)}
            disabled={!products || submitting}
            required
          >
            {!products && <option value="">Loading products…</option>}
            {products?.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name} · {formatMoney(item.price)} · {item.available} available
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Quantity</span>
          <input
            type="number"
            min={1}
            max={1000}
            value={qty}
            onChange={(event) => setQty(Math.max(1, Math.min(1000, Number(event.target.value) || 1)))}
            disabled={submitting}
            required
          />
        </label>
        {product && (
          <p className="dialog__hint">
            Total {formatMoney(product.price * qty)}
            {qty > product.available && " — more than available, so the reservation will fail"}
          </p>
        )}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
        <div className="dialog__actions">
          <button className="button button--secondary" type="button" onClick={onClose} disabled={submitting}>
            Cancel
          </button>
          <button className="button" type="submit" disabled={!product || submitting}>
            {submitting ? "Placing…" : "Place order"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
