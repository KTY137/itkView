export type ProductVariant = "flow" | "view";

export type Product = {
  variant: ProductVariant;
  name: "itkFlow" | "itkView";
  brandPrefix: "itk";
  brandAccent: "Flow" | "View";
  csrfCookie: "itkflow_csrf" | "itkview_csrf";
  /** Production-workflow writes, including ingest, Outbox and stage changes. */
  workflowWrites: boolean;
};

export function productForVariant(rawVariant: string | undefined): Product {
  const variant: ProductVariant = rawVariant?.trim().toLowerCase() === "view" ? "view" : "flow";
  if (variant === "view") {
    return {
      variant,
      name: "itkView",
      brandPrefix: "itk",
      brandAccent: "View",
      csrfCookie: "itkview_csrf",
      workflowWrites: false,
    };
  }
  return {
    variant,
    name: "itkFlow",
    brandPrefix: "itk",
    brandAccent: "Flow",
    csrfCookie: "itkflow_csrf",
    workflowWrites: true,
  };
}

export const product = productForVariant(import.meta.env.VITE_ITKFLOW_PRODUCT_VARIANT);
export const isViewProduct = product.variant === "view";

export function setProductDocumentTitle(
  selectedProduct: Product,
  target: Pick<Document, "title">,
): void {
  target.title = selectedProduct.name;
}
