"use client";

import { use } from "react";
import { RegisterDetail } from "../../register";

export default function Page({ params }) {
  const { id } = use(params);
  return <RegisterDetail kind="clients" id={id} />;
}
