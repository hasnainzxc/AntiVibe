import { NextApiRequest, NextApiResponse } from "next";

function requireAuth(
  handler: (req: NextApiRequest, res: NextApiResponse) => void,
) {
  return (req: NextApiRequest, res: NextApiResponse) => {
    const token = req.headers.authorization;
    if (!token || !token.startsWith("Bearer ")) {
      return res.status(401).json({ error: "Unauthorized" });
    }
    return handler(req, res);
  };
}

function handler(req: NextApiRequest, res: NextApiResponse) {
  return res.status(200).json({ message: "This is protected data" });
}

export default requireAuth(handler);
